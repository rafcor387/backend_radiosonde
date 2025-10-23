import os
from io import StringIO
import re, json
import numpy as np
import pandas as pd
import metpy.calc as mpcalc
from metpy.units import units

# ==== Config ====
_P = list(np.arange(620.0, 100.0, -20.0, dtype=float))
if _P[-1] != 100.0: _P.append(100.0)
P_LEVELS = np.array(_P, dtype=float)      # descendente
P_LEVELS_ASC = np.sort(P_LEVELS)          # ascendente para interp

FEATURE_ORDER = [
    "p_hPa","z_m","T_K","Td_K","RH_0_1","u_ms","v_ms",
    "theta_K","theta_v_K","Gamma_env_Kkm","dtheta_dz_Kkm","N2_s2"
]
CLASSES = ["Inversion", "Inestable", "Neutral", "Estable"]

G = 9.806
GAMMA_DRY = 9.8
HEADER_LINE_IDX = 45   # cabecera en la línea 46 (1-based)

RENAME_MAP = {
    "P": "P", "Height": "Z", "T": "T", "TD": "TD",
    "RH": "RH", "u": "u", "v": "v", "MR": "MR",
    "DD": "DD", "FF": "FF",
}

# ---- Lectura (desde path o file-like) ----
def read_edt_tsv(source) -> pd.DataFrame:
    """
    source: ruta (str/Path) o file-like (UploadedFile, BytesIO, etc).
    Asegura modo texto para pandas.read_csv.
    """
    # Caso 1: ruta en disco
    if isinstance(source, (str, os.PathLike)):
        df = pd.read_csv(source, sep="\t", skiprows=HEADER_LINE_IDX, engine="python")
    else:
        # Caso 2: file-like (bytes). Leemos y decodificamos a texto.
        raw = source.read()
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            # Ya es str
            text = raw
        buf = StringIO(text)
        df = pd.read_csv(buf, sep="\t", skiprows=HEADER_LINE_IDX, engine="python")

    df.columns = df.columns.str.strip()
    cols_lower = {c.lower(): c for c in df.columns}
    selected = {}
    for src, dst in RENAME_MAP.items():
        if src in df.columns:
            selected[src] = dst
        elif src.lower() in cols_lower:
            selected[cols_lower[src.lower()]] = dst
    df = df[list(selected.keys())].rename(columns=selected)
    for c in df.columns:
        df[c] = df[c].astype(float)
    return df.sort_values("P").reset_index(drop=True)

# ---- Interpolación ----
def interp_to_levels(df: pd.DataFrame):
    p = df["P"].to_numpy()
    I = lambda y: np.interp(P_LEVELS_ASC, p, y)
    Z  = I(df["Z"].to_numpy())
    T  = I(df["T"].to_numpy())
    TD = I(df["TD"].to_numpy())
    RH = I(df["RH"].to_numpy()) if "RH" in df else np.full_like(T, 50.0)
    U  = I(df["u"].to_numpy())  if "u"  in df else np.zeros_like(T)
    V  = I(df["v"].to_numpy())  if "v"  in df else np.zeros_like(T)
    MR = I(df["MR"].to_numpy()) if "MR" in df else np.zeros_like(T)
    D = lambda a: a[::-1]
    return (P_LEVELS.copy(), D(Z), D(T), D(TD), D(RH), D(U), D(V), D(MR))

# ---- Utilidades físicas ----
def ensure_monotonic_z(z):
    z = z.copy()
    for i in range(1, len(z)):
        if z[i] <= z[i-1]:
            z[i] = z[i-1] + 1.0
    return z

def moving_mean(x, k=5):
    if k <= 1 or len(x) < 3: return x
    pad = k // 2
    xx = np.pad(x, (pad, pad), mode='edge')
    return np.convolve(xx, np.ones(k)/k, mode='valid')

def grad_dz(z, f, smooth_k=5):
    ff = moving_mean(f, k=smooth_k) if smooth_k > 1 else f
    n = min(len(z), len(ff))
    return np.gradient(ff[:n], z[:n])

def _first_scalar(q):
    try: return q[0]
    except Exception: return q

def _mixed_layer_T_Td(p_q, T_q, Td_q, depth=50*units.hectopascal):
    try:
        res = mpcalc.mixed_layer(p_q, T_q, Td_q, depth=depth)
        if isinstance(res, tuple):
            if len(res) == 3: _, T_ml, Td_ml = res; return _first_scalar(T_ml), _first_scalar(Td_ml)
            if len(res) == 2: T_ml, Td_ml = res;   return _first_scalar(T_ml), _first_scalar(Td_ml)
    except Exception:
        pass
    try:
        res2 = mpcalc.mixed_layer(T_q, Td_q, p_q, depth=depth)
        if isinstance(res2, tuple) and len(res2) >= 2:
            T_ml, Td_ml = res2[:2]; return _first_scalar(T_ml), _first_scalar(Td_ml)
    except Exception:
        pass
    return _first_scalar(T_q), _first_scalar(Td_q)

def physics_from_profile(p_hPa, z_m, T_K, Td_K, RH_pct, u_ms, v_ms, MR_gkg):
    z_m = ensure_monotonic_z(z_m)

    p_q = (p_hPa * units.hectopascal)
    T_q = (T_K  * units.kelvin)
    Td_q= (Td_K * units.kelvin)
    if np.allclose(MR_gkg, 0.0):
        rh01_q = (RH_pct/100.0) * units.dimensionless
        r_q = mpcalc.mixing_ratio_from_relative_humidity(rh01_q, T_q, p_q)
    else:
        r_q = (MR_gkg/1000.0) * units('kg/kg')

    theta   = mpcalc.potential_temperature(p_q, T_q).m
    theta_v = mpcalc.virtual_potential_temperature(p_q, T_q, r_q).m

    dT_dz     = grad_dz(z_m, T_K, smooth_k=5)
    Gamma_env = -dT_dz * 1000.0

    T_parcel_sb = mpcalc.parcel_profile(p_q, T_q[0], Td_q[0]).to('kelvin')
    T_ml0, Td_ml0 = _mixed_layer_T_Td(p_q, T_q, Td_q, depth=50*units.hectopascal)
    T_parcel_ml = mpcalc.parcel_profile(p_q, T_ml0, Td_ml0).to('kelvin')

    dTp_dz_ml   = grad_dz(z_m, T_parcel_ml.m, smooth_k=5)
    Gamma_moist = -dTp_dz_ml * 1000.0

    try:
        cape_sb, cin_sb = mpcalc.cape_cin(p_q, T_q, Td_q, T_parcel_sb)
        cape_ml, cin_ml = mpcalc.cape_cin(p_q, T_q, Td_q, T_parcel_ml)
        cape_sb = cape_sb.to('J/kg').m; cin_sb = cin_sb.to('J/kg').m
        cape_ml = cape_ml.to('J/kg').m; cin_ml = cin_ml.to('J/kg').m
    except Exception:
        cape_sb = cin_sb = cape_ml = cin_ml = np.nan

    dtheta_dz = grad_dz(z_m, theta,   smooth_k=5) * 1000.0
    dthv_dz   = grad_dz(z_m, theta_v, smooth_k=5)
    N2        = (G / theta_v) * dthv_dz

    return dict(
        theta=theta, theta_v=theta_v,
        Gamma_env=Gamma_env, Gamma_moist=Gamma_moist, Gamma_dry=np.full_like(Gamma_env, GAMMA_DRY),
        dtheta_dz_Kkm=dtheta_dz, N2=N2,
        cape_sb=cape_sb, cin_sb=cin_sb, cape_ml=cape_ml, cin_ml=cin_ml,
        z=z_m
    )

def label_from_metrics(z_m, T_K, Gamma_env, Gamma_moist, N2,
                       z_sfc=None, cape_sb=np.nan, cin_sb=np.nan,
                       cape_ml=np.nan, cin_ml=np.nan):
    if z_sfc is None: z_sfc = z_m[0]
    z_agl = z_m - z_sfc

    dT_dz = -Gamma_env/1000.0
    inv = (dT_dz > 0) & (z_agl <= 500)
    if np.any(inv):
        idx = np.where(inv)[0]; s = idx[0]; ok = False
        for i in range(1, len(idx)):
            if idx[i] != idx[i-1] + 1:
                if (z_agl[idx[i-1]] - z_agl[s]) >= 150: ok = True
                s = idx[i]
        if (z_agl[idx[-1]] - z_agl[s]) >= 150: ok = True
        if ok: return "Inversion"

    if (np.isfinite(cape_ml) and cape_ml >= 50 and (np.isnan(cin_ml) or cin_ml > -75)) \
       or (np.isfinite(cape_sb) and cape_sb >= 100 and (np.isnan(cin_sb) or cin_sb > -100)):
        return "Inestable"

    diff = (Gamma_env - Gamma_moist) > 0.5
    if np.any(diff):
        idx = np.where(diff)[0]; s = idx[0]
        for i in range(1, len(idx)):
            if idx[i] != idx[i-1] + 1:
                if (z_agl[idx[i-1]] - z_agl[s]) >= 400: return "Inestable"
                s = idx[i]
        if (z_agl[idx[-1]] - z_agl[s]) >= 400: return "Inestable"

    negN = N2 < -2e-4
    if np.any(negN):
        idx = np.where(negN)[0]; s = idx[0]
        for i in range(1, len(idx)):
            if idx[i] != idx[i-1] + 1:
                if (z_agl[idx[i-1]] - z_agl[s]) >= 200: return "Inestable"
                s = idx[i]
        if (z_agl[idx[-1]] - z_agl[s]) >= 200: return "Inestable"

    m03 = (z_agl >= 0) & (z_agl <= 3000)
    GamE = np.nanmean(Gamma_env[m03])
    GamM = np.nanmean(Gamma_moist[m03])
    N2m  = np.nanmean(N2[m03])
    if GamE < (GamM - 0.3) and (np.isnan(N2m) or N2m > 1e-4):
        return "Estable"
    return "Neutral"

def build_feature_matrix(p, z, T, Td, RHpct, u, v, phys):
    RH01 = np.clip(RHpct/100.0, 0, 1)
    X = np.stack([
        p, z, T, Td, RH01, u, v,
        phys["theta"], phys["theta_v"], phys["Gamma_env"],
        phys["dtheta_dz_Kkm"], phys["N2"]
    ], axis=1).astype(np.float64)
    return X

def process_uploaded_tsv(uploaded_file, filename="radiosonde.tsv"):
    """Procesa un TSV (file-like) y devuelve el dict JSON con resumen, niveles y etiqueta."""
    df = read_edt_tsv(uploaded_file)
    p, z, T, Td, RH, u, v, MR = interp_to_levels(df)
    z = ensure_monotonic_z(z)

    phys = physics_from_profile(p, z, T, Td, RH, u, v, MR)
    label = label_from_metrics(
        phys["z"], T, phys["Gamma_env"], phys["Gamma_moist"], phys["N2"], z_sfc=phys["z"][0],
        cape_sb=phys.get("cape_sb", np.nan), cin_sb=phys.get("cin_sb", np.nan),
        cape_ml=phys.get("cape_ml", np.nan), cin_ml=phys.get("cin_ml", np.nan)
    )
    X = build_feature_matrix(p, z, T, Td, RH, u, v, phys)

    z_agl = z - z[0]; m03 = (z_agl >= 0) & (z_agl <= 3000)
    summary = {
        "Gamma_env_0_3km": float(np.nanmean(phys["Gamma_env"][m03])),
        "Gamma_moist_0_3km": float(np.nanmean(phys["Gamma_moist"][m03])),
        "N2_mean_0_3km": float(np.nanmean(phys["N2"][m03])),
        "CAPE_SB": float(phys.get("cape_sb", np.nan)),
        "CIN_SB": float(phys.get("cin_sb", np.nan)),
        "CAPE_ML": float(phys.get("cape_ml", np.nan)),
        "CIN_ML": float(phys.get("cin_ml", np.nan)),
    }
    levels = [{k: float(v) for k, v in zip(FEATURE_ORDER, row)} for row in X]
    # fecha opcional desde nombre
    date_from_name = ""
    m = re.search(r"(\d{8})", filename)
    if m:
        raw = m.group(1); mm, dd, yyyy = raw[:2], raw[2:4], raw[4:]
        date_from_name = f"{yyyy}-{mm}-{dd}"

    return {
        "file": filename,
        "date": date_from_name,
        "label": label,
        "summary": summary,
        "levels": levels
    }
