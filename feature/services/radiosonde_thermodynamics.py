from dataclasses import dataclass
import warnings

import metpy
import metpy.calc as mpcalc
from metpy.units import units
import numpy as np

from .radiosonde_normalizer import NormalizedRadiosonde, normalize_radiosonde


MIN_ENERGY_LEVELS = 10
MIN_ENERGY_DEPTH_HPA = 50.0
MIXED_LAYER_DEPTH_HPA = 50.0
MOST_UNSTABLE_DEPTH_HPA = 300.0


class RadiosondeThermodynamicsError(Exception):
    """El perfil no permite producir un análisis termodinámico fiable."""


@dataclass
class ThermodynamicAnalysis:
    pressure: object
    temperature: object
    dewpoint: object
    height_agl: object
    surface_parcel: object
    level_markers: dict
    parcels: dict
    levels: dict
    indices: dict
    lapse_rates: dict
    downdraft: dict
    warnings: list[str]

    def diagram_diagnostics(self) -> dict:
        """Contrato compacto consumido por el Skew-T."""
        return {
            "surface_based": _energy_only(self.parcels["surface_based"]),
            "mixed_layer_50hpa": _energy_only(
                self.parcels["mixed_layer_50hpa"]
            ),
            "most_unstable_300hpa": _energy_only(
                self.parcels["most_unstable_300hpa"]
            ),
            "levels": {
                f"{name}_pressure_hpa": values["pressure_hpa"]
                for name, values in self.levels.items()
            },
            "indices": dict(self.indices),
        }

    def stability_cape(self) -> dict:
        """Contrato de CAPE/CIN consumido por la clasificación de estabilidad."""
        return {
            "surface_based": _energy_only(self.parcels["surface_based"]),
            "mixed_layer_50hpa": _energy_only(
                self.parcels["mixed_layer_50hpa"]
            ),
        }


def analyze_radiosonde_thermodynamics(profile_id: int) -> dict:
    """Recupera, normaliza y analiza la termodinámica de un radiosondeo."""
    return analyze_normalized_thermodynamics(normalize_radiosonde(profile_id))


def analyze_normalized_thermodynamics(normalized: NormalizedRadiosonde) -> dict:
    analysis = calculate_thermodynamics(normalized)
    return {
        "profile": normalized.general_response()["profile"],
        "parcels": analysis.parcels,
        "levels": analysis.levels,
        "indices": analysis.indices,
        "lapse_rates": analysis.lapse_rates,
        "downdraft": analysis.downdraft,
        "quality": {
            "normalized_levels": len(normalized.dataframe),
            "normalization_status": normalized.quality["status"],
            "warnings": (
                list(normalized.quality.get("warnings", [])) + analysis.warnings
            ),
        },
        "methodology": {
            "metpy_version": metpy.__version__,
            "mixed_layer_depth_hpa": MIXED_LAYER_DEPTH_HPA,
            "most_unstable_search_depth_hpa": MOST_UNSTABLE_DEPTH_HPA,
            "height_reference": "AGL",
            "parcel_level_selection": "LFC y EL superiores (which=top)",
            "dcape": (
                "MetPy downdraft_cape; requiere la capa 700–500 hPa y se "
                "reporta no disponible si 700 hPa está bajo la superficie"
            ),
            "not_used": [
                {
                    "indices": ["K Index", "Total Totals", "Showalter"],
                    "reason": (
                        "Requieren 850 hPa, nivel situado debajo de la "
                        "superficie del radiosondeo de La Paz."
                    ),
                }
            ],
        },
    }


def calculate_thermodynamics(
    normalized: NormalizedRadiosonde,
) -> ThermodynamicAnalysis:
    """Fuente única de diagnósticos termodinámicos MetPy."""
    dataframe = normalized.dataframe
    pressure = dataframe["pressure_hpa"].to_numpy(dtype=float) * units.hPa
    temperature = dataframe["temperature_k"].to_numpy(dtype=float) * units.kelvin
    dewpoint = dataframe["dewpoint_k"].to_numpy(dtype=float) * units.kelvin
    height_msl = dataframe["height_msl_m"].to_numpy(dtype=float) * units.meter
    height_agl = height_msl - height_msl[0]
    if len(pressure) < 2:
        raise RadiosondeThermodynamicsError(
            "Se requieren al menos dos niveles termodinámicos válidos."
        )

    try:
        surface_parcel = mpcalc.parcel_profile(
            pressure,
            temperature[0],
            dewpoint[0],
        ).to("kelvin")
    except Exception as exc:
        raise RadiosondeThermodynamicsError(
            f"No se pudo calcular la parcela superficial: {exc}"
        ) from exc

    calculation_warnings = []
    metpy_warnings = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parcels = _calculate_parcels(
            pressure,
            temperature,
            dewpoint,
            surface_parcel,
            calculation_warnings,
        )
        levels, level_markers, convective_temperature = _calculate_levels(
            pressure,
            temperature,
            dewpoint,
            height_agl,
            surface_parcel,
            calculation_warnings,
        )
        indices = _calculate_indices(
            pressure,
            temperature,
            dewpoint,
            height_agl,
            surface_parcel,
            convective_temperature,
            calculation_warnings,
        )
        lapse_rates = _calculate_lapse_rates(
            height_agl,
            temperature,
            calculation_warnings,
        )
        downdraft = _calculate_downdraft(
            pressure,
            temperature,
            dewpoint,
            height_agl,
            calculation_warnings,
        )
        for item in caught:
            message = str(item.message)
            if message not in metpy_warnings:
                metpy_warnings.append(message)

    return ThermodynamicAnalysis(
        pressure=pressure,
        temperature=temperature,
        dewpoint=dewpoint,
        height_agl=height_agl,
        surface_parcel=surface_parcel,
        level_markers=level_markers,
        parcels=parcels,
        levels=levels,
        indices=indices,
        lapse_rates=lapse_rates,
        downdraft=downdraft,
        warnings=calculation_warnings + metpy_warnings,
    )


def _calculate_parcels(
    pressure,
    temperature,
    dewpoint,
    surface_parcel,
    warning_messages,
):
    parcels = {
        "surface_based": {
            "origin": _origin_payload(pressure[0], temperature[0], dewpoint[0]),
            "cape_j_kg": None,
            "cin_j_kg": None,
        },
        "mixed_layer_50hpa": {
            "origin": None,
            "cape_j_kg": None,
            "cin_j_kg": None,
        },
        "most_unstable_300hpa": {
            "origin": None,
            "source_level_index": None,
            "cape_j_kg": None,
            "cin_j_kg": None,
        },
    }
    available_depth = pressure[0] - pressure[-1]
    if (
        len(pressure) >= MIN_ENERGY_LEVELS
        and available_depth >= MIN_ENERGY_DEPTH_HPA * units.hPa
    ):
        try:
            cape, cin = mpcalc.surface_based_cape_cin(
                pressure, temperature, dewpoint
            )
            parcels["surface_based"].update(_cape_cin_values(cape, cin))
        except Exception as exc:
            warning_messages.append(f"No se pudo calcular SB CAPE/CIN: {exc}")

    if available_depth >= MIXED_LAYER_DEPTH_HPA * units.hPa:
        try:
            origin_pressure, origin_temperature, origin_dewpoint = mpcalc.mixed_parcel(
                pressure,
                temperature,
                dewpoint,
                depth=MIXED_LAYER_DEPTH_HPA * units.hPa,
            )
            cape, cin = mpcalc.mixed_layer_cape_cin(
                pressure,
                temperature,
                dewpoint,
                depth=MIXED_LAYER_DEPTH_HPA * units.hPa,
            )
            parcels["mixed_layer_50hpa"]["origin"] = _origin_payload(
                origin_pressure,
                origin_temperature,
                origin_dewpoint,
            )
            parcels["mixed_layer_50hpa"].update(_cape_cin_values(cape, cin))
        except Exception as exc:
            warning_messages.append(f"No se pudo calcular ML50 CAPE/CIN: {exc}")

    if available_depth >= MOST_UNSTABLE_DEPTH_HPA * units.hPa:
        try:
            origin_pressure, origin_temperature, origin_dewpoint, index = (
                mpcalc.most_unstable_parcel(
                    pressure,
                    temperature,
                    dewpoint,
                    depth=MOST_UNSTABLE_DEPTH_HPA * units.hPa,
                )
            )
            cape, cin = mpcalc.most_unstable_cape_cin(
                pressure,
                temperature,
                dewpoint,
                depth=MOST_UNSTABLE_DEPTH_HPA * units.hPa,
            )
            parcels["most_unstable_300hpa"]["origin"] = _origin_payload(
                origin_pressure,
                origin_temperature,
                origin_dewpoint,
            )
            parcels["most_unstable_300hpa"]["source_level_index"] = int(index)
            parcels["most_unstable_300hpa"].update(_cape_cin_values(cape, cin))
        except Exception as exc:
            warning_messages.append(f"No se pudo calcular MU300 CAPE/CIN: {exc}")
    return parcels


def _calculate_levels(
    pressure,
    temperature,
    dewpoint,
    height_agl,
    surface_parcel,
    warning_messages,
):
    levels = {
        name: {
            "pressure_hpa": None,
            "temperature_c": None,
            "height_agl_m": None,
        }
        for name in ("lcl", "lfc", "el", "ccl")
    }
    markers = {}
    convective_temperature = None

    try:
        level_pressure, level_temperature = mpcalc.lcl(
            pressure[0], temperature[0], dewpoint[0]
        )
        levels["lcl"] = _level_payload(
            level_pressure, level_temperature, pressure, height_agl
        )
        markers["LCL"] = (level_pressure, level_temperature)
    except Exception as exc:
        warning_messages.append(f"No se pudo calcular LCL: {exc}")

    try:
        level_pressure, level_temperature = mpcalc.lfc(
            pressure,
            temperature,
            dewpoint,
            parcel_temperature_profile=surface_parcel,
            which="top",
        )
        levels["lfc"] = _level_payload(
            level_pressure, level_temperature, pressure, height_agl
        )
        if levels["lfc"]["pressure_hpa"] is not None:
            markers["LFC"] = (level_pressure, level_temperature)
    except Exception as exc:
        warning_messages.append(f"No se pudo calcular LFC: {exc}")

    try:
        level_pressure, level_temperature = mpcalc.el(
            pressure,
            temperature,
            dewpoint,
            parcel_temperature_profile=surface_parcel,
            which="top",
        )
        levels["el"] = _level_payload(
            level_pressure, level_temperature, pressure, height_agl
        )
        if levels["el"]["pressure_hpa"] is not None:
            markers["EL"] = (level_pressure, level_temperature)
    except Exception as exc:
        warning_messages.append(f"No se pudo calcular EL: {exc}")

    try:
        level_pressure, level_temperature, convective_temperature = mpcalc.ccl(
            pressure,
            temperature,
            dewpoint,
            which="top",
        )
        levels["ccl"] = _level_payload(
            level_pressure, level_temperature, pressure, height_agl
        )
    except Exception as exc:
        warning_messages.append(f"No se pudo calcular CCL: {exc}")
    return levels, markers, convective_temperature


def _calculate_indices(
    pressure,
    temperature,
    dewpoint,
    height_agl,
    surface_parcel,
    convective_temperature,
    warning_messages,
):
    result = {
        "lifted_index_c": None,
        "precipitable_water_mm": None,
        "convective_temperature_c": _quantity_number(
            convective_temperature, "degC"
        ),
        "freezing_level_agl_m": _freezing_level_agl(temperature, height_agl),
    }
    if pressure[0] >= 500 * units.hPa and pressure[-1] <= 500 * units.hPa:
        try:
            result["lifted_index_c"] = _quantity_number(
                mpcalc.lifted_index(pressure, temperature, surface_parcel),
                "delta_degC",
            )
        except Exception as exc:
            warning_messages.append(f"No se pudo calcular Lifted Index: {exc}")
    try:
        result["precipitable_water_mm"] = _quantity_number(
            mpcalc.precipitable_water(pressure, dewpoint),
            "mm",
        )
    except Exception as exc:
        warning_messages.append(f"No se pudo calcular agua precipitable: {exc}")
    return result


def _calculate_lapse_rates(height_agl, temperature, warning_messages):
    result = {"0_3km_c_km": None, "3_6km_c_km": None}
    height_km = height_agl.to("km").magnitude
    temperature_c = temperature.to("degC").magnitude
    for bottom, top, key in (
        (0.0, 3.0, "0_3km_c_km"),
        (3.0, 6.0, "3_6km_c_km"),
    ):
        if height_km[0] > bottom or height_km[-1] < top:
            continue
        try:
            bottom_temperature = float(np.interp(bottom, height_km, temperature_c))
            top_temperature = float(np.interp(top, height_km, temperature_c))
            result[key] = round((bottom_temperature - top_temperature) / (top - bottom), 2)
        except (TypeError, ValueError) as exc:
            warning_messages.append(
                f"No se pudo calcular el gradiente {bottom:g}–{top:g} km: {exc}"
            )
    return result


def _calculate_downdraft(
    pressure,
    temperature,
    dewpoint,
    height_agl,
    warning_messages,
):
    result = {
        "available": False,
        "method": "metpy_downdraft_cape_700_500hpa",
        "reason": None,
        "dcape_j_kg": None,
        "origin_pressure_hpa": None,
        "origin_height_agl_m": None,
        "surface_parcel_temperature_c": None,
    }
    if pressure[0] < 700 * units.hPa:
        result["reason"] = (
            "MetPy downdraft_cape requiere 700 hPa, nivel situado debajo de "
            "la superficie de esta estación de alta elevación."
        )
        return result
    if pressure[-1] > 500 * units.hPa:
        result["reason"] = "El perfil no alcanza 500 hPa."
        return result
    try:
        dcape, down_pressure, down_trace = mpcalc.downdraft_cape(
            pressure, temperature, dewpoint
        )
        origin_pressure = down_pressure[-1]
        result.update(
            {
                "available": True,
                "dcape_j_kg": _quantity_number(dcape, "J/kg"),
                "origin_pressure_hpa": _quantity_number(origin_pressure, "hPa"),
                "origin_height_agl_m": _pressure_height_agl(
                    origin_pressure, pressure, height_agl
                ),
                "surface_parcel_temperature_c": _quantity_number(
                    down_trace[0], "degC"
                ),
            }
        )
    except Exception as exc:
        result["reason"] = str(exc)
        warning_messages.append(f"No se pudo calcular DCAPE: {exc}")
    return result


def _origin_payload(pressure, temperature, dewpoint):
    return {
        "pressure_hpa": _quantity_number(pressure, "hPa"),
        "temperature_c": _quantity_number(temperature, "degC"),
        "dewpoint_c": _quantity_number(dewpoint, "degC"),
    }


def _level_payload(level_pressure, level_temperature, pressure, height_agl):
    return {
        "pressure_hpa": _quantity_number(level_pressure, "hPa"),
        "temperature_c": _quantity_number(level_temperature, "degC"),
        "height_agl_m": _pressure_height_agl(
            level_pressure, pressure, height_agl
        ),
    }


def _pressure_height_agl(level_pressure, pressure, height_agl):
    pressure_value = _quantity_number(level_pressure, "hPa", digits=5)
    if pressure_value is None:
        return None
    pressure_values = pressure.to("hPa").magnitude
    if pressure_value > pressure_values[0] or pressure_value < pressure_values[-1]:
        return None
    height_values = height_agl.to("meter").magnitude
    height = np.interp(
        np.log(pressure_value),
        np.log(pressure_values[::-1]),
        height_values[::-1],
    )
    return round(float(height), 1)


def _freezing_level_agl(temperature, height_agl):
    temperature_c = temperature.to("degC").magnitude
    height_m = height_agl.to("meter").magnitude
    crossing = np.flatnonzero(
        (temperature_c[:-1] > 0.0) & (temperature_c[1:] <= 0.0)
    )
    if not crossing.size:
        return 0.0 if temperature_c[0] <= 0.0 else None
    index = int(crossing[0])
    delta = temperature_c[index] - temperature_c[index + 1]
    fraction = 0.0 if delta == 0 else temperature_c[index] / delta
    height = height_m[index] + fraction * (height_m[index + 1] - height_m[index])
    return round(float(height), 1)


def _cape_cin_values(cape, cin):
    return {
        "cape_j_kg": _quantity_number(cape, "J/kg"),
        "cin_j_kg": _quantity_number(cin, "J/kg"),
    }


def _energy_only(parcel):
    return {
        "cape_j_kg": parcel["cape_j_kg"],
        "cin_j_kg": parcel["cin_j_kg"],
    }


def _quantity_number(quantity, unit: str, digits: int = 1):
    if quantity is None:
        return None
    try:
        values = np.asarray(quantity.to(unit).magnitude, dtype=float).reshape(-1)
    except (AttributeError, TypeError, ValueError):
        return None
    finite = values[np.isfinite(values)]
    if not finite.size:
        return None
    return round(float(finite[0]), digits)
