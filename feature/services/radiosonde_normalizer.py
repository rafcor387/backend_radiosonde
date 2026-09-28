from dataclasses import dataclass
from datetime import timezone

import numpy as np
import pandas as pd

from .radiosonde_source import LoadedRadiosondeSource, load_radiosonde_source


COLUMN_MAP = {
    "time": "elapsed_time_s",
    "P": "pressure_hpa",
    "Height": "height_msl_m",
    "T": "temperature_k",
    "TD": "dewpoint_k",
    "RH": "relative_humidity_pct",
    "u": "u_wind_ms",
    "v": "v_wind_ms",
    "FF": "wind_speed_ms",
    "DD": "wind_direction_deg",
    "MR": "mixing_ratio_gkg",
    "Lat": "latitude_deg",
    "Lon": "longitude_deg",
}
REQUIRED_COLUMNS = {
    "elapsed_time_s",
    "pressure_hpa",
    "height_msl_m",
    "temperature_k",
    "dewpoint_k",
}
OPTIONAL_COLUMNS = set(COLUMN_MAP.values()).difference(REQUIRED_COLUMNS)
MISSING_SENTINEL = -32768.0


class RadiosondeNormalizationError(Exception):
    """El perfil no contiene suficientes datos físicos para normalizarse."""


@dataclass
class NormalizedRadiosonde:
    source: LoadedRadiosondeSource
    dataframe: pd.DataFrame
    quality: dict

    def general_response(self) -> dict:
        dataframe = self.dataframe
        surface = dataframe.iloc[0]
        top = dataframe.iloc[-1]

        return {
            "profile": {
                "profile_id": self.source.record.pk,
                "date": self.source.record.date.isoformat(),
                "time": (
                    self.source.record.time.strftime("%H:%MZ")
                    if self.source.record.time
                    else None
                ),
                "observed_at": _iso_z(self.source.record.observed_at),
                "station": self.source.station,
                "launch_time": _iso_z(self.source.launch_time),
            },
            "quality": self.quality,
            "coverage": {
                "levels": len(dataframe),
                "surface_pressure_hpa": _number(surface["pressure_hpa"]),
                "top_pressure_hpa": _number(top["pressure_hpa"]),
                "pressure_depth_hpa": _number(
                    surface["pressure_hpa"] - top["pressure_hpa"]
                ),
                "surface_height_msl_m": _number(surface["height_msl_m"]),
                "top_height_msl_m": _number(top["height_msl_m"]),
                "top_height_agl_m": _number(
                    top["height_msl_m"] - surface["height_msl_m"]
                ),
                "duration_seconds": _number(dataframe["elapsed_time_s"].max()),
            },
            "surface": _level_response(surface),
            "top": _level_response(top),
            "launch_location": {
                "latitude_deg": _first_valid(dataframe, "latitude_deg"),
                "longitude_deg": _first_valid(dataframe, "longitude_deg"),
            },
            "available_variables": list(dataframe.columns),
        }


def normalize_radiosonde(profile_id: int) -> NormalizedRadiosonde:
    """Recupera desde R2 y normaliza un radiosondeo en memoria."""
    return normalize_loaded_source(load_radiosonde_source(profile_id))


def normalize_loaded_source(source: LoadedRadiosondeSource) -> NormalizedRadiosonde:
    raw = source.dataframe.copy()
    original_rows = len(raw)
    available_raw_columns = [column for column in COLUMN_MAP if column in raw.columns]
    dataframe = raw[available_raw_columns].rename(columns=COLUMN_MAP)

    missing_required = REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing_required:
        raise RadiosondeNormalizationError(
            "Faltan columnas requeridas: "
            + ", ".join(sorted(missing_required))
            + "."
        )

    for column in dataframe.columns:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")

    sentinel_values = int((dataframe == MISSING_SENTINEL).sum().sum())
    dataframe = dataframe.replace(
        [MISSING_SENTINEL, np.inf, -np.inf],
        np.nan,
    )

    missing_required_mask = dataframe[list(REQUIRED_COLUMNS)].isna().any(axis=1)
    rows_missing_required = int(missing_required_mask.sum())
    dataframe = dataframe.loc[~missing_required_mask].copy()

    physical_mask = (
        dataframe["pressure_hpa"].between(1.0, 1100.0)
        & dataframe["temperature_k"].between(150.0, 350.0)
        & dataframe["dewpoint_k"].between(130.0, 350.0)
        & dataframe["height_msl_m"].between(-1000.0, 60000.0)
        & dataframe["elapsed_time_s"].ge(0.0)
    )
    rows_outside_physical_limits = int((~physical_mask).sum())
    dataframe = dataframe.loc[physical_mask].copy()

    dataframe = dataframe.sort_values(
        ["pressure_hpa", "elapsed_time_s"],
        ascending=[False, True],
    )
    duplicate_pressures = int(dataframe.duplicated("pressure_hpa").sum())
    dataframe = dataframe.drop_duplicates("pressure_hpa", keep="first")

    dewpoint_above_temperature = int(
        (dataframe["dewpoint_k"] > dataframe["temperature_k"]).sum()
    )
    dataframe["dewpoint_k"] = dataframe[["dewpoint_k", "temperature_k"]].min(
        axis=1
    )

    relative_humidity_clipped = 0
    if "relative_humidity_pct" in dataframe:
        relative_humidity_clipped = int(
            (
                dataframe["relative_humidity_pct"].notna()
                & ~dataframe["relative_humidity_pct"].between(0.0, 100.0)
            ).sum()
        )
        dataframe["relative_humidity_pct"] = dataframe[
            "relative_humidity_pct"
        ].clip(0.0, 100.0)

    monotonic_mask = _strictly_increasing_height_mask(dataframe["height_msl_m"])
    non_increasing_height_rows = int((~monotonic_mask).sum())
    dataframe = dataframe.loc[monotonic_mask].reset_index(drop=True)

    if len(dataframe) < 2:
        raise RadiosondeNormalizationError(
            "El perfil no conserva al menos dos niveles válidos después del control de calidad."
        )

    missing_optional = sorted(OPTIONAL_COLUMNS.difference(dataframe.columns))
    warnings = []
    if sentinel_values:
        warnings.append(f"Se reemplazaron {sentinel_values} valores -32768 por nulos.")
    if rows_missing_required:
        warnings.append(
            f"Se eliminaron {rows_missing_required} filas con variables requeridas ausentes."
        )
    if rows_outside_physical_limits:
        warnings.append(
            f"Se eliminaron {rows_outside_physical_limits} filas fuera de límites físicos."
        )
    if duplicate_pressures:
        warnings.append(
            f"Se eliminaron {duplicate_pressures} niveles de presión duplicados."
        )
    if dewpoint_above_temperature:
        warnings.append(
            f"Se ajustaron {dewpoint_above_temperature} valores de rocío mayores que la temperatura."
        )
    if relative_humidity_clipped:
        warnings.append(
            f"Se limitaron {relative_humidity_clipped} valores de humedad relativa al rango 0-100 %."
        )
    if non_increasing_height_rows:
        warnings.append(
            f"Se eliminaron {non_increasing_height_rows} filas con altura no creciente."
        )
    if missing_optional:
        warnings.append(
            "Variables opcionales ausentes: " + ", ".join(missing_optional) + "."
        )

    if len(dataframe) < 20:
        status = "invalid"
        warnings.append("El perfil conserva menos de 20 niveles válidos.")
    elif warnings:
        status = "valid_with_warnings"
    else:
        status = "valid"

    quality = {
        "status": status,
        "original_rows": original_rows,
        "normalized_rows": len(dataframe),
        "removed_rows": original_rows - len(dataframe),
        "sentinel_values_replaced": sentinel_values,
        "rows_missing_required": rows_missing_required,
        "rows_outside_physical_limits": rows_outside_physical_limits,
        "duplicate_pressures_removed": duplicate_pressures,
        "dewpoint_values_clamped": dewpoint_above_temperature,
        "relative_humidity_values_clipped": relative_humidity_clipped,
        "non_increasing_height_rows_removed": non_increasing_height_rows,
        "pressure_strictly_decreasing": bool(
            (dataframe["pressure_hpa"].diff().dropna() < 0).all()
        ),
        "height_strictly_increasing": bool(
            (dataframe["height_msl_m"].diff().dropna() > 0).all()
        ),
        "warnings": warnings,
    }

    return NormalizedRadiosonde(
        source=source,
        dataframe=dataframe,
        quality=quality,
    )


def _strictly_increasing_height_mask(height: pd.Series) -> pd.Series:
    keep = []
    last_height = -np.inf
    for value in height.to_numpy(dtype=float):
        is_valid = value > last_height
        keep.append(is_valid)
        if is_valid:
            last_height = value
    return pd.Series(keep, index=height.index, dtype=bool)


def _level_response(row: pd.Series) -> dict:
    return {
        "pressure_hpa": _number(row.get("pressure_hpa")),
        "height_msl_m": _number(row.get("height_msl_m")),
        "temperature_k": _number(row.get("temperature_k")),
        "temperature_c": _number(row.get("temperature_k") - 273.15),
        "dewpoint_k": _number(row.get("dewpoint_k")),
        "dewpoint_c": _number(row.get("dewpoint_k") - 273.15),
        "relative_humidity_pct": _number(row.get("relative_humidity_pct")),
        "wind_speed_ms": _number(row.get("wind_speed_ms")),
        "wind_direction_deg": _number(row.get("wind_direction_deg")),
        "u_wind_ms": _number(row.get("u_wind_ms")),
        "v_wind_ms": _number(row.get("v_wind_ms")),
        "mixing_ratio_gkg": _number(row.get("mixing_ratio_gkg")),
    }


def _first_valid(dataframe: pd.DataFrame, column: str):
    if column not in dataframe:
        return None
    values = dataframe[column].dropna()
    return _number(values.iloc[0]) if not values.empty else None


def _number(value):
    if value is None or pd.isna(value):
        return None
    return round(float(value), 3)


def _iso_z(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
