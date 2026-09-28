from dataclasses import dataclass
import hashlib
from io import BytesIO
import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from metpy.plots import Hodograph
from metpy.units import units
import numpy as np
from botocore.exceptions import BotoCoreError, ClientError

from .r2_client import get_r2_client
from .radiosonde_normalizer import NormalizedRadiosonde, normalize_radiosonde
from .radiosonde_wind import calculate_wind_diagnostics, prepare_wind_profile


PLOT_VERSION = "v2"
MAX_HODOGRAPH_BYTES = 5 * 1024 * 1024
HEIGHT_MARKERS_KM = (0.0, 1.0, 3.0, 6.0, 9.0, 12.0)


class RadiosondeHodographError(Exception):
    """Error controlado al generar, guardar o recuperar un hodógrafo."""


@dataclass
class HodographArtifact:
    profile_id: int
    bucket: str
    object_key: str
    source_sha256: str
    filename: str
    size_bytes: int
    cached: bool
    diagnostics: dict
    png_bytes: bytes | None = None

    def descriptor(self, normalized: NormalizedRadiosonde) -> dict:
        profile = normalized.general_response()["profile"]
        public_path = f"/api/radiosondes/{self.profile_id}/hodograph/image"
        return {
            "type": "hodograph_diagram",
            "profile": profile,
            "image_path": public_path,
            "download_path": f"{public_path}?download=true",
            "filename": self.filename,
            "content_type": "image/png",
            "size_bytes": self.size_bytes,
            "plot_version": PLOT_VERSION,
            "source_sha256": self.source_sha256,
            "cached": self.cached,
            "diagnostics": self.diagnostics,
            "summary": (
                "Hodógrafo 0–12 km AGL coloreado por altura, con niveles "
                "característicos y cizalladura vectorial por capas."
            ),
        }


def get_or_create_hodograph(
    profile_id: int,
) -> tuple[HodographArtifact, NormalizedRadiosonde]:
    """Normaliza el perfil y garantiza que su hodógrafo exista en R2."""
    normalized = normalize_radiosonde(profile_id)
    wind_profile = prepare_wind_profile(normalized)
    diagnostics = calculate_wind_diagnostics(wind_profile)
    source_hash = hashlib.sha256(normalized.source.raw_bytes).hexdigest()
    object_key = (
        f"derived/hodograph/{PLOT_VERSION}/profile-{profile_id}/{source_hash}.png"
    )
    filename = _filename(normalized)
    bucket = normalized.source.record.bucket
    client = get_r2_client()

    cached_size = _cached_size(client, bucket, object_key)
    if cached_size is not None:
        return (
            HodographArtifact(
                profile_id=profile_id,
                bucket=bucket,
                object_key=object_key,
                source_sha256=source_hash,
                filename=filename,
                size_bytes=cached_size,
                cached=True,
                diagnostics=diagnostics,
            ),
            normalized,
        )

    png_bytes = render_hodograph_png(
        normalized,
        wind_profile=wind_profile,
        diagnostics=diagnostics,
    )
    if len(png_bytes) > MAX_HODOGRAPH_BYTES:
        raise RadiosondeHodographError(
            f"El PNG generado supera el límite de {MAX_HODOGRAPH_BYTES} bytes."
        )

    try:
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=png_bytes,
            ContentType="image/png",
            CacheControl="private, max-age=3600",
            Metadata={
                "profile-id": str(profile_id),
                "source-sha256": source_hash,
                "plot-version": PLOT_VERSION,
            },
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise RadiosondeHodographError(
            f"R2 rechazó el guardado del hodógrafo: {code}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeHodographError(
            "No se pudo conectar con R2 para guardar el hodógrafo."
        ) from exc

    return (
        HodographArtifact(
            profile_id=profile_id,
            bucket=bucket,
            object_key=object_key,
            source_sha256=source_hash,
            filename=filename,
            size_bytes=len(png_bytes),
            cached=False,
            diagnostics=diagnostics,
            png_bytes=png_bytes,
        ),
        normalized,
    )


def load_hodograph_png(profile_id: int) -> tuple[HodographArtifact, bytes]:
    """Devuelve el PNG cacheado, generándolo primero cuando sea necesario."""
    artifact, _ = get_or_create_hodograph(profile_id)
    if artifact.png_bytes is not None:
        return artifact, artifact.png_bytes

    client = get_r2_client()
    try:
        response = client.get_object(Bucket=artifact.bucket, Key=artifact.object_key)
    except (ClientError, BotoCoreError) as exc:
        raise RadiosondeHodographError(
            "No se pudo recuperar el hodógrafo almacenado en R2."
        ) from exc

    body = response["Body"]
    try:
        png_bytes = body.read(MAX_HODOGRAPH_BYTES + 1)
    finally:
        body.close()
    if len(png_bytes) > MAX_HODOGRAPH_BYTES:
        raise RadiosondeHodographError(
            f"El PNG supera el límite de {MAX_HODOGRAPH_BYTES} bytes."
        )
    return artifact, png_bytes


def render_hodograph_png(
    normalized: NormalizedRadiosonde,
    wind_profile: dict | None = None,
    diagnostics: dict | None = None,
) -> bytes:
    """Renderiza un hodógrafo PNG íntegramente en memoria."""
    wind_profile = wind_profile or prepare_wind_profile(normalized)
    diagnostics = diagnostics or calculate_wind_diagnostics(wind_profile)
    u = wind_profile["u_ms"]
    v = wind_profile["v_ms"]
    height_km = wind_profile["height_agl_km"]
    component_range = _component_range(u, v)

    figure = plt.figure(figsize=(11.5, 7.5), dpi=140)
    try:
        layout = figure.add_gridspec(
            1,
            2,
            width_ratios=(3.4, 1.25),
            wspace=0.26,
        )
        axis = figure.add_subplot(layout[0])
        diagnostics_axis = figure.add_subplot(layout[1])
        hodograph = Hodograph(axis, component_range=component_range)
        hodograph.add_grid(increment=5, color="#cbd5e1", linewidth=0.6)
        hodograph.add_grid(
            increment=10,
            color="#94a3b8",
            linewidth=0.9,
            linestyle="-",
        )
        colored_line = hodograph.plot_colormapped(
            u * units("m/s"),
            v * units("m/s"),
            height_km * units.km,
            cmap="viridis",
            linewidth=2.8,
        )
        colorbar = figure.colorbar(
            colored_line,
            ax=axis,
            fraction=0.046,
            pad=0.04,
        )
        colorbar.set_label("Altura AGL (km)")

        _plot_height_markers(axis, wind_profile)
        _plot_diagnostics_panel(diagnostics_axis, diagnostics)

        profile = normalized.general_response()["profile"]
        station = profile.get("station") or "La Paz"
        valid_time = profile.get("observed_at") or (
            f"{profile['date']} {profile.get('time') or ''}".strip()
        )
        axis.set_title(f"Hodógrafo — {station}", loc="left", fontsize=12, weight="bold")
        axis.set_title(valid_time, loc="right", fontsize=9)
        axis.set_xlabel("Componente U (m/s)")
        axis.set_ylabel("Componente V (m/s)")

        buffer = BytesIO()
        figure.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            facecolor="white",
            metadata={"Software": f"MetPy hodograph {PLOT_VERSION}"},
        )
        return buffer.getvalue()
    except Exception as exc:
        raise RadiosondeHodographError(
            f"No se pudo renderizar el hodógrafo: {exc}"
        ) from exc
    finally:
        plt.close(figure)


def _plot_height_markers(axis, wind_profile):
    u = wind_profile["u_ms"]
    v = wind_profile["v_ms"]
    height = wind_profile["height_agl_km"]
    label_offsets = {
        0.0: (6, -14),
        1.0: (6, 7),
        3.0: (7, 4),
        6.0: (7, 4),
        9.0: (7, 4),
        12.0: (7, 4),
    }
    for marker_height in HEIGHT_MARKERS_KM:
        if marker_height < height[0] or marker_height > height[-1]:
            continue
        marker_u = float(np.interp(marker_height, height, u))
        marker_v = float(np.interp(marker_height, height, v))
        axis.scatter(
            marker_u,
            marker_v,
            s=32,
            color="white",
            edgecolor="#0f172a",
            linewidth=1.0,
            zorder=5,
        )
        axis.annotate(
            f"{marker_height:g} km",
            (marker_u, marker_v),
            xytext=label_offsets[marker_height],
            textcoords="offset points",
            fontsize=7.5,
            fontweight="bold",
            color="#0f172a",
            zorder=6,
        )


def _plot_diagnostics_panel(axis, diagnostics):
    axis.set_axis_off()
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.0)
    axis.text(
        0.03,
        0.97,
        "DIAGNÓSTICO DE VIENTO",
        fontsize=11.5,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    y = 0.88
    y = _panel_section(axis, y, "COBERTURA")
    layer = diagnostics["plotted_layer"]
    y = _panel_value(axis, y, "Tope AGL", layer["top_agl_km"], "km")
    y = _panel_value(axis, y, "Niveles de viento", layer["wind_levels"], "")

    y = _panel_section(axis, y - 0.02, "VIENTO")
    surface = diagnostics["surface_wind"]
    y = _panel_value(axis, y, "Superficie", surface["speed_ms"], "m/s")
    y = _panel_value(
        axis,
        y,
        "Dirección desde",
        surface["direction_from_deg"],
        "°",
    )
    maximum = diagnostics["maximum_wind"]
    y = _panel_value(axis, y, "Máximo", maximum["speed_ms"], "m/s")
    y = _panel_value(axis, y, "Altura del máximo", maximum["height_agl_km"], "km")

    y = _panel_section(axis, y - 0.02, "CIZALLADURA VECTORIAL")
    for label, key in (
        ("0–1 km", "0_1km"),
        ("0–3 km", "0_3km"),
        ("0–6 km", "0_6km"),
    ):
        shear = diagnostics["bulk_shear"][key]
        value = None if shear is None else shear["speed_ms"]
        y = _panel_value(axis, y, label, value, "m/s")

    axis.text(
        0.03,
        0.035,
        "Dirección meteorológica: origen del viento.\n"
        "La cizalladura es la magnitud del vector ΔV.",
        fontsize=7.5,
        color="#475569",
        va="bottom",
    )


def _panel_section(axis, y, title):
    axis.text(
        0.03,
        y,
        title,
        fontsize=8.5,
        fontweight="bold",
        color="#334155",
        va="top",
    )
    return y - 0.052


def _panel_value(axis, y, label, value, unit):
    if value is None:
        formatted = "—"
    elif unit:
        formatted = f"{value:.1f} {unit}"
    else:
        formatted = str(value)
    axis.text(
        0.03,
        y,
        f"{label}: {formatted}",
        fontsize=8,
        fontweight="bold",
        color="#0f172a",
        va="top",
    )
    return y - 0.045


def _component_range(u, v) -> float:
    maximum = float(np.nanmax(np.abs(np.concatenate([u, v]))))
    return max(20.0, math.ceil((maximum + 2.0) / 5.0) * 5.0)


def _cached_size(client, bucket: str, object_key: str) -> int | None:
    try:
        response = client.head_object(Bucket=bucket, Key=object_key)
        return int(response.get("ContentLength") or 0)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
            return None
        raise RadiosondeHodographError(
            f"R2 rechazó la consulta de caché del hodógrafo: {code or 'Unknown'}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeHodographError(
            "No se pudo consultar la caché del hodógrafo en R2."
        ) from exc


def _filename(normalized: NormalizedRadiosonde) -> str:
    record = normalized.source.record
    time_part = record.time.strftime("%H%MZ") if record.time else "sin-hora"
    return f"hodografo-LPZ-{record.date.isoformat()}-{time_part}.png"
