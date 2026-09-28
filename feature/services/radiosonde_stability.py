from dataclasses import dataclass
import warnings

import metpy
import metpy.calc as mpcalc
from metpy.units import units
import numpy as np
import pandas as pd

from .radiosonde_normalizer import NormalizedRadiosonde, normalize_radiosonde
from .radiosonde_thermodynamics import calculate_thermodynamics


MIN_LEVELS = 20
ANALYSIS_DEPTH_M = 3000.0
GRID_STEP_M = 25.0
DRY_ADIABATIC_LAPSE_RATE_C_KM = 9.8
NEUTRAL_TOLERANCE_C_KM = 0.1
SIGNIFICANT_INVERSION_DEPTH_M = 150.0


class RadiosondeStabilityError(Exception):
    """El perfil no permite producir un diagnóstico de estabilidad fiable."""


@dataclass
class Layer:
    present: bool
    base_agl_m: float | None = None
    top_agl_m: float | None = None
    depth_m: float = 0.0

    def as_dict(self) -> dict:
        return {
            "present": self.present,
            "base_agl_m": _number(self.base_agl_m),
            "top_agl_m": _number(self.top_agl_m),
            "depth_m": _number(self.depth_m),
        }


def classify_radiosonde_stability(profile_id: int) -> dict:
    """Recupera, normaliza y diagnostica físicamente un radiosondeo."""
    return classify_normalized_stability(normalize_radiosonde(profile_id))


def classify_normalized_stability(
    normalized: NormalizedRadiosonde,
    thermodynamics=None,
) -> dict:
    """Genera un diagnóstico multieje mediante MetPy y reglas transparentes."""
    dataframe = normalized.dataframe
    if len(dataframe) < MIN_LEVELS:
        raise RadiosondeStabilityError(
            f"Se requieren al menos {MIN_LEVELS} niveles válidos para "
            "diagnosticar la estabilidad."
        )

    pressure = dataframe["pressure_hpa"].to_numpy(dtype=float) * units.hPa
    temperature = dataframe["temperature_k"].to_numpy(dtype=float) * units.kelvin
    dewpoint = dataframe["dewpoint_k"].to_numpy(dtype=float) * units.kelvin
    height_msl = dataframe["height_msl_m"].to_numpy(dtype=float)
    height_agl = height_msl - height_msl[0]

    if float(height_agl[-1]) < ANALYSIS_DEPTH_M:
        raise RadiosondeStabilityError(
            "El perfil no alcanza los 3000 m AGL requeridos para este diagnóstico."
        )

    calculation_warnings = []
    metpy_warnings = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thermodynamics = thermodynamics or calculate_thermodynamics(normalized)
        cape = thermodynamics.stability_cape()
        calculation_warnings.extend(
            warning
            for warning in thermodynamics.warnings
            if "CAPE/CIN" in warning
        )
        try:
            vertical = _calculate_vertical_metrics(
                pressure,
                temperature,
                height_agl,
            )
        except Exception as exc:
            raise RadiosondeStabilityError(
                f"No se pudieron calcular las métricas verticales: {exc}"
            ) from exc

        for item in caught:
            message = str(item.message)
            if message not in metpy_warnings:
                metpy_warnings.append(message)

    static_axis = _static_stability_axis(vertical["brunt_vaisala_n2_s2"])
    parcel_axis = _parcel_stability_axis(
        vertical["environmental_lapse_rate_c_km"],
        vertical["moist_adiabatic_lapse_rate_c_km"],
    )
    convective_axis = _convective_potential_axis(cape)
    inversion_axis = _surface_inversion_axis(vertical)

    overall_code, overall_label, summary = _overall_diagnosis(
        static_axis,
        parcel_axis,
        convective_axis,
        inversion_axis,
    )

    profile = normalized.general_response()["profile"]
    all_warnings = (
        list(normalized.quality.get("warnings", []))
        + calculation_warnings
        + metpy_warnings
    )

    return {
        "profile": profile,
        "classification": {
            "code": overall_code,
            "label": overall_label,
            "method": "layered_metpy_diagnosis_v2",
            "summary": summary,
            "single_label_is_simplification": True,
        },
        "axes": {
            "static_stability_0_3km": static_axis,
            "parcel_lapse_rate_0_3km": parcel_axis,
            "convective_potential": convective_axis,
            "surface_inversion": inversion_axis,
        },
        "metrics": {
            "surface_based": cape["surface_based"],
            "mixed_layer_50hpa": cape["mixed_layer_50hpa"],
            "layer_0_3km": {
                "environmental_lapse_rate_c_km": _mean_number(
                    vertical["environmental_lapse_rate_c_km"]
                ),
                "moist_adiabatic_lapse_rate_c_km": _mean_number(
                    vertical["moist_adiabatic_lapse_rate_c_km"]
                ),
                "mean_brunt_vaisala_n2_s2": _mean_number(
                    vertical["brunt_vaisala_n2_s2"],
                    digits=7,
                ),
            },
        },
        "quality": {
            "normalized_levels": len(dataframe),
            "analyzed_depth_agl_m": ANALYSIS_DEPTH_M,
            "normalization_status": normalized.quality["status"],
            "warnings": all_warnings,
        },
        "methodology": {
            "metpy_version": metpy.__version__,
            "framework": {
                "static_stability": "signo de N²",
                "parcel_stability": (
                    "comparación del gradiente ambiental con los gradientes "
                    "adiabáticos húmedo y seco"
                ),
                "convective_potential": (
                    "CAPE/CIN de parcela de superficie y capa mezclada de 50 hPa"
                ),
            },
            "analysis_depth_agl_m": ANALYSIS_DEPTH_M,
            "classification_grid_step_m": GRID_STEP_M,
            "dry_adiabatic_lapse_rate_c_km": DRY_ADIABATIC_LAPSE_RATE_C_KM,
            "neutral_numerical_tolerance_c_km": NEUTRAL_TOLERANCE_C_KM,
            "configured_significant_inversion_depth_m": (
                SIGNIFICANT_INVERSION_DEPTH_M
            ),
            "operational_guides": [
                {
                    "name": "NWS CAPE qualitative ranges",
                    "purpose": "Descripción operativa, no frontera física universal.",
                }
            ],
            "not_used": [
                {
                    "indices": ["K Index", "Total Totals", "Showalter"],
                    "reason": (
                        "Requieren el nivel de 850 hPa, situado debajo de la "
                        "superficie del sondeo de La Paz."
                    ),
                }
            ],
            "disclaimer": (
                "Diagnóstico por capas. La categoría global resume el perfil y "
                "no sustituye sus ejes físicos ni el criterio meteorológico."
            ),
        },
    }


def _calculate_vertical_metrics(pressure, temperature, height_agl):
    potential_temperature = mpcalc.potential_temperature(pressure, temperature)
    n2 = mpcalc.brunt_vaisala_frequency_squared(
        height_agl * units.meter,
        potential_temperature,
    ).to("1/s^2").magnitude
    moist_profile = mpcalc.moist_lapse(pressure, temperature[0]).to(
        "degC"
    ).magnitude
    temperature_c = temperature.to("degC").magnitude

    grid = np.arange(0.0, ANALYSIS_DEPTH_M + GRID_STEP_M, GRID_STEP_M)
    temperature_grid = _smooth(np.interp(grid, height_agl, temperature_c))
    moist_grid = _smooth(np.interp(grid, height_agl, moist_profile))
    n2_grid = _smooth(np.interp(grid, height_agl, n2))

    return {
        "height_agl_m": grid,
        "temperature_c": temperature_grid,
        "environmental_lapse_rate_c_km": (
            -np.gradient(temperature_grid, grid) * 1000.0
        ),
        "moist_adiabatic_lapse_rate_c_km": (
            -np.gradient(moist_grid, grid) * 1000.0
        ),
        "brunt_vaisala_n2_s2": n2_grid,
    }


def _static_stability_axis(n2):
    stable = n2 > 0.0
    neutral = n2 == 0.0
    unstable = n2 < 0.0
    fractions = {
        "stable_fraction": _fraction(stable),
        "neutral_fraction": _fraction(neutral),
        "unstable_fraction": _fraction(unstable),
    }
    active = sum(value > 0.0 for value in fractions.values())
    if active > 1:
        code, label = "mixed", "Mixta por capas"
    elif fractions["stable_fraction"]:
        code, label = "stable", "Estable"
    elif fractions["unstable_fraction"]:
        code, label = "unstable", "Inestable"
    else:
        code, label = "neutral", "Neutral"
    return {
        "code": code,
        "label": label,
        "basis": "N² > 0 estable; N² = 0 neutral; N² < 0 inestable",
        "mean_n2_s2": _mean_number(n2, digits=7),
        **fractions,
    }


def _parcel_stability_axis(environmental, moist):
    dry = DRY_ADIABATIC_LAPSE_RATE_C_KM
    tolerance = NEUTRAL_TOLERANCE_C_KM
    neutral_moist = np.isclose(environmental, moist, atol=tolerance, rtol=0.0)
    neutral_dry = np.isclose(environmental, dry, atol=tolerance, rtol=0.0)
    neutral = neutral_moist | neutral_dry
    absolutely_stable = (environmental < moist - tolerance) & ~neutral
    absolutely_unstable = (environmental > dry + tolerance) & ~neutral
    conditionally_unstable = ~(
        neutral | absolutely_stable | absolutely_unstable
    )

    fractions = {
        "absolutely_stable_fraction": _fraction(absolutely_stable),
        "conditionally_unstable_fraction": _fraction(conditionally_unstable),
        "absolutely_unstable_fraction": _fraction(absolutely_unstable),
        "neutral_fraction": _fraction(neutral),
    }
    dominant_key = max(fractions, key=fractions.get)
    dominant_code = dominant_key.removesuffix("_fraction")
    active = sum(value > 0.0 for value in fractions.values())
    return {
        "code": "mixed" if active > 1 else dominant_code,
        "label": "Mixta por capas" if active > 1 else _parcel_label(dominant_code),
        "dominant_regime": dominant_code,
        "basis": (
            "comparación de los gradientes húmedo, ambiental y seco"
        ),
        **fractions,
    }


def _convective_potential_axis(cape):
    mlcape = cape["mixed_layer_50hpa"]["cape_j_kg"]
    mlcin = cape["mixed_layer_50hpa"]["cin_j_kg"]
    if mlcape is None:
        code, label = "unavailable", "No disponible"
    elif mlcape <= 0.0:
        code, label = "none", "Sin CAPE positivo"
    elif mlcape < 1000.0:
        code, label = "marginal", "Débil o marginal"
    elif mlcape < 2500.0:
        code, label = "moderate", "Moderado"
    elif mlcape < 4000.0:
        code, label = "very_unstable", "Muy inestable"
    else:
        code, label = "extreme", "Extremo"
    return {
        "code": code,
        "label": label,
        "parcel": "mixed_layer_50hpa",
        "cape_j_kg": mlcape,
        "cin_j_kg": mlcin,
        "cape_positive": mlcape is not None and mlcape > 0.0,
        "guide": (
            "Rangos cualitativos operativos del NWS; dependen de región, "
            "estación y parcela, y no son fronteras universales."
        ),
    }


def _surface_inversion_axis(vertical):
    grid = vertical["height_agl_m"]
    temperature = vertical["temperature_c"]
    gamma = vertical["environmental_lapse_rate_c_km"]
    layer = _longest_true_layer(grid, (gamma < 0.0) & (grid <= 500.0))
    payload = layer.as_dict()
    payload["significant_by_configured_threshold"] = (
        layer.present and layer.depth_m >= SIGNIFICANT_INVERSION_DEPTH_M
    )
    if layer.present:
        bottom = int(np.argmin(np.abs(grid - layer.base_agl_m)))
        top = int(np.argmin(np.abs(grid - layer.top_agl_m)))
        payload["temperature_change_c"] = _number(
            temperature[top] - temperature[bottom]
        )
    else:
        payload["temperature_change_c"] = None
    payload["basis"] = "temperatura creciente con la altura dentro de 0–500 m AGL"
    return payload


def _overall_diagnosis(static, parcel, convective, inversion):
    if (
        static["code"] == "stable"
        and parcel["code"] == "absolutely_stable"
        and not convective["cape_positive"]
    ):
        return (
            "stable",
            "Estable",
            "Los ejes estático, de parcela y convectivo coinciden en estabilidad.",
        )
    if (
        static["code"] == "unstable"
        and parcel["code"] == "absolutely_unstable"
    ):
        return (
            "unstable",
            "Inestable",
            "Los diagnósticos estático y de parcela coinciden en inestabilidad.",
        )
    if static["code"] == "neutral" and parcel["code"] == "neutral":
        return (
            "neutral",
            "Neutral",
            "Los diagnósticos estático y de parcela son aproximadamente neutrales.",
        )

    signals = [
        f"estabilidad estática {static['label'].lower()}",
        f"estabilidad de parcela {parcel['label'].lower()}",
        f"potencial convectivo {convective['label'].lower()}",
    ]
    if inversion["present"]:
        signals.append("inversión superficial presente")
    return (
        "mixed",
        "Perfil mixto",
        "El perfil cambia con la altura: " + "; ".join(signals) + ".",
    )


def _longest_true_layer(grid, mask):
    best_start = None
    best_end = None
    current_start = None
    for index, active in enumerate(mask):
        if active and current_start is None:
            current_start = index
        if current_start is not None and (not active or index == len(mask) - 1):
            current_end = index if active and index == len(mask) - 1 else index - 1
            if best_start is None or (
                grid[current_end] - grid[current_start]
                > grid[best_end] - grid[best_start]
            ):
                best_start, best_end = current_start, current_end
            current_start = None
    if best_start is None:
        return Layer(present=False)
    return Layer(
        present=True,
        base_agl_m=float(grid[best_start]),
        top_agl_m=float(grid[best_end]),
        depth_m=float(grid[best_end] - grid[best_start]),
    )


def _smooth(values, window=5):
    return (
        pd.Series(values)
        .rolling(window=window, center=True, min_periods=1)
        .mean()
        .to_numpy(dtype=float)
    )


def _fraction(mask):
    return round(float(np.mean(mask)), 4)


def _parcel_label(code):
    return {
        "absolutely_stable": "Absolutamente estable",
        "conditionally_unstable": "Condicionalmente inestable",
        "absolutely_unstable": "Absolutamente inestable",
        "neutral": "Neutral",
    }[code]


def _number(value, digits=3):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def _mean_number(values, digits=3):
    value = float(np.nanmean(values))
    if not np.isfinite(value):
        raise RadiosondeStabilityError(
            "No se pudieron obtener métricas verticales finitas en 0–3 km AGL."
        )
    return round(value, digits)
