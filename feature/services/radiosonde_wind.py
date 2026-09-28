import metpy
import metpy.calc as mpcalc
from metpy.units import units
import numpy as np

from .radiosonde_normalizer import NormalizedRadiosonde, normalize_radiosonde


MAX_ANALYSIS_HEIGHT_AGL_KM = 12.0
SURFACE_TOLERANCE_KM = 0.1
LAYER_DEPTHS_KM = (1.0, 3.0, 6.0)


class RadiosondeWindError(Exception):
    """El perfil no permite producir un análisis de viento fiable."""


def analyze_radiosonde_wind(profile_id: int) -> dict:
    """Recupera, normaliza y analiza el viento de un radiosondeo."""
    return analyze_normalized_wind(normalize_radiosonde(profile_id))


def analyze_normalized_wind(normalized: NormalizedRadiosonde) -> dict:
    """Calcula diagnósticos cinemáticos mediante MetPy."""
    wind_profile = prepare_wind_profile(normalized)
    diagnostics = calculate_wind_diagnostics(wind_profile)
    calculation_warnings = diagnostics.pop("calculation_warnings")
    return {
        "profile": normalized.general_response()["profile"],
        **diagnostics,
        "quality": {
            "normalization_status": normalized.quality["status"],
            "warnings": (
                list(normalized.quality.get("warnings", []))
                + calculation_warnings
            ),
        },
        "methodology": {
            "metpy_version": metpy.__version__,
            "height_reference": "AGL",
            "maximum_analysis_height_km": MAX_ANALYSIS_HEIGHT_AGL_KM,
            "bulk_shear": "MetPy bulk_shear",
            "mean_wind": "MetPy mean_pressure_weighted",
            "storm_motion": "MetPy Bunkers storm motion",
            "storm_relative_helicity": (
                "MetPy storm_relative_helicity respecto al Bunkers right mover"
            ),
            "direction_conventions": {
                "wind": "dirección meteorológica desde donde sopla",
                "vectors": "dirección hacia donde apunta el vector",
            },
        },
    }


def prepare_wind_profile(normalized: NormalizedRadiosonde) -> dict:
    """Extrae un perfil U/V finito, creciente en altura y limitado a 12 km AGL."""
    dataframe = normalized.dataframe
    required = {"pressure_hpa", "u_wind_ms", "v_wind_ms", "height_msl_m"}
    if not required.issubset(dataframe.columns):
        raise RadiosondeWindError(
            "El radiosondeo no contiene presión, altura y componentes U/V."
        )

    pressure = dataframe["pressure_hpa"].to_numpy(dtype=float)
    u = dataframe["u_wind_ms"].to_numpy(dtype=float)
    v = dataframe["v_wind_ms"].to_numpy(dtype=float)
    height_msl = dataframe["height_msl_m"].to_numpy(dtype=float)
    height_agl_km = (height_msl - height_msl[0]) / 1000.0
    valid = (
        np.isfinite(pressure)
        & np.isfinite(u)
        & np.isfinite(v)
        & np.isfinite(height_agl_km)
        & (height_agl_km >= 0.0)
        & (height_agl_km <= MAX_ANALYSIS_HEIGHT_AGL_KM)
    )
    pressure = pressure[valid]
    u = u[valid]
    v = v[valid]
    height_agl_km = height_agl_km[valid]
    if len(u) < 2:
        raise RadiosondeWindError(
            "Se requieren al menos dos niveles de viento válidos entre 0 y 12 km AGL."
        )

    unique_height, unique_indices = np.unique(height_agl_km, return_index=True)
    pressure = pressure[unique_indices]
    u = u[unique_indices]
    v = v[unique_indices]
    if np.any(np.diff(pressure) >= 0.0):
        raise RadiosondeWindError(
            "La presión del perfil de viento no disminuye estrictamente con la altura."
        )
    return {
        "pressure_hpa": pressure,
        "u_ms": u,
        "v_ms": v,
        "height_agl_km": unique_height,
    }


def calculate_wind_diagnostics(wind_profile: dict) -> dict:
    """Calcula viento, capas, Bunkers y SRH sobre un perfil preparado."""
    pressure = wind_profile["pressure_hpa"] * units.hPa
    u = wind_profile["u_ms"] * units("m/s")
    v = wind_profile["v_ms"] * units("m/s")
    height = wind_profile["height_agl_km"] * units.km
    speed = mpcalc.wind_speed(u, v)
    maximum_index = int(np.nanargmax(speed.to("m/s").magnitude))
    warnings = []

    result = {
        "plotted_layer": {
            "base_agl_km": _quantity_number(height[0], "km", 2),
            "top_agl_km": _quantity_number(height[-1], "km", 2),
            "wind_levels": int(len(height)),
        },
        "surface_wind": _wind_vector(u[0], v[0]),
        "maximum_wind": {
            **_wind_vector(u[maximum_index], v[maximum_index]),
            "height_agl_km": _quantity_number(height[maximum_index], "km", 2),
        },
        "layers": {},
        "bulk_shear": {},
        "storm_motion": {
            "method": "bunkers",
            "available": False,
            "right_mover": None,
            "left_mover": None,
            "mean_wind_0_6km": None,
        },
        "storm_relative_helicity": {
            "reference_motion": "bunkers_right_mover",
            "0_1km": None,
            "0_3km": None,
        },
        "calculation_warnings": warnings,
    }

    starts_at_surface = float(height[0].to("km").magnitude) <= SURFACE_TOLERANCE_KM
    for depth_km in LAYER_DEPTHS_KM:
        key = f"0_{int(depth_km)}km"
        if not starts_at_surface or height[-1] < depth_km * units.km:
            result["layers"][key] = {
                "available": False,
                "depth_km": depth_km,
                "bulk_shear": None,
                "mean_wind": None,
            }
            result["bulk_shear"][key] = None
            continue
        try:
            shear_u, shear_v = mpcalc.bulk_shear(
                pressure,
                u,
                v,
                height=height,
                bottom=0 * units.km,
                depth=depth_km * units.km,
            )
            mean_u, mean_v = mpcalc.mean_pressure_weighted(
                pressure,
                u,
                v,
                height=height,
                bottom=0 * units.km,
                depth=depth_km * units.km,
            )
            shear = _vector(shear_u, shear_v, direction_convention="to")
            result["layers"][key] = {
                "available": True,
                "depth_km": depth_km,
                "bulk_shear": shear,
                "mean_wind": _wind_vector(mean_u, mean_v),
            }
            result["bulk_shear"][key] = shear
        except (ValueError, IndexError) as exc:
            result["layers"][key] = {
                "available": False,
                "depth_km": depth_km,
                "bulk_shear": None,
                "mean_wind": None,
            }
            result["bulk_shear"][key] = None
            warnings.append(f"No se pudo calcular la capa 0–{depth_km:g} km: {exc}")

    right_mover = None
    if starts_at_surface and height[-1] >= 6 * units.km:
        try:
            right_mover, left_mover, mean_wind = mpcalc.bunkers_storm_motion(
                pressure,
                u,
                v,
                height,
            )
            result["storm_motion"] = {
                "method": "bunkers",
                "available": True,
                "right_mover": _vector(
                    right_mover[0], right_mover[1], direction_convention="to"
                ),
                "left_mover": _vector(
                    left_mover[0], left_mover[1], direction_convention="to"
                ),
                "mean_wind_0_6km": _wind_vector(mean_wind[0], mean_wind[1]),
            }
        except (ValueError, IndexError) as exc:
            warnings.append(f"No se pudo calcular el movimiento Bunkers: {exc}")

    if right_mover is not None:
        for depth_km in (1.0, 3.0):
            key = f"0_{int(depth_km)}km"
            if height[-1] < depth_km * units.km:
                continue
            try:
                positive, negative, total = mpcalc.storm_relative_helicity(
                    height,
                    u,
                    v,
                    depth_km * units.km,
                    bottom=0 * units.km,
                    storm_u=right_mover[0],
                    storm_v=right_mover[1],
                )
                result["storm_relative_helicity"][key] = {
                    "positive_m2_s2": _quantity_number(positive, "m^2/s^2"),
                    "negative_m2_s2": _quantity_number(negative, "m^2/s^2"),
                    "total_m2_s2": _quantity_number(total, "m^2/s^2"),
                }
            except (ValueError, IndexError) as exc:
                warnings.append(f"No se pudo calcular SRH 0–{depth_km:g} km: {exc}")

    return result


def _wind_vector(u, v) -> dict:
    return _vector(u, v, direction_convention="from")


def _vector(u, v, direction_convention: str) -> dict:
    speed = mpcalc.wind_speed(u, v)
    direction = mpcalc.wind_direction(u, v, convention=direction_convention)
    direction_key = (
        "direction_from_deg" if direction_convention == "from" else "direction_to_deg"
    )
    return {
        "u_ms": _quantity_number(u, "m/s"),
        "v_ms": _quantity_number(v, "m/s"),
        "speed_ms": _quantity_number(speed, "m/s"),
        direction_key: _quantity_number(direction, "degree"),
    }


def _quantity_number(quantity, unit: str, digits: int = 1) -> float | None:
    try:
        value = float(np.asarray(quantity.to(unit).magnitude).reshape(-1)[0])
    except (AttributeError, TypeError, ValueError, IndexError):
        return None
    if not np.isfinite(value):
        return None
    return round(value, digits)
