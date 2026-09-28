import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO

import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError

from feature.models import RadiosondeProfile

from .r2_client import get_r2_client


MAX_RADIOSONDE_BYTES = 10 * 1024 * 1024
REQUIRED_COLUMNS = {"time", "P", "T", "TD", "Height"}
SYNOPTIC_TIME_TOLERANCE_MINUTES = 60


class RadiosondeSourceError(Exception):
    """Error controlado al localizar, descargar o reconocer un TSV."""


@dataclass
class LoadedRadiosondeSource:
    record: RadiosondeProfile
    raw_bytes: bytes
    dataframe: pd.DataFrame
    station: str | None
    launch_time: datetime | None
    etag: str | None

    def inspection(self) -> dict:
        pressure = pd.to_numeric(self.dataframe["P"], errors="coerce").dropna()
        catalog_time = (
            self.record.time.strftime("%H:%MZ") if self.record.time else None
        )
        launch_time = _datetime_to_iso_z(self.launch_time)

        date_matches = (
            self.launch_time.date() == self.record.date if self.launch_time else None
        )
        hour_matches = (
            _matches_synoptic_time(self.launch_time, self.record.time)
            if self.launch_time and self.record.time
            else None
        )

        warnings = []
        if date_matches is False:
            warnings.append(
                "La fecha de lanzamiento del TSV no coincide con la fecha del catálogo."
            )
        if hour_matches is False:
            warnings.append(
                "La hora de lanzamiento del TSV no coincide con la hora sinóptica del catálogo."
            )

        return {
            "profile": {
                "profile_id": self.record.pk,
                "date": self.record.date.isoformat(),
                "time": catalog_time,
                "observed_at": _datetime_to_iso_z(self.record.observed_at),
            },
            "storage": {
                "bucket": self.record.bucket,
                "object_key": self.record.object_key,
                "size_bytes": len(self.raw_bytes),
                "etag": self.etag,
                "sha256": hashlib.sha256(self.raw_bytes).hexdigest(),
            },
            "source": {
                "station": self.station,
                "launch_time": launch_time,
                "rows": len(self.dataframe),
                "columns": list(self.dataframe.columns),
                "surface_pressure_hpa": (
                    float(pressure.max()) if not pressure.empty else None
                ),
                "top_pressure_hpa": (
                    float(pressure.min()) if not pressure.empty else None
                ),
            },
            "catalog_match": {
                "date": date_matches,
                "synoptic_hour": hour_matches,
            },
            "warnings": warnings,
        }


def load_radiosonde_source(profile_id: int) -> LoadedRadiosondeSource:
    """Descarga desde R2 y reconoce el TSV asociado a un profile_id."""
    try:
        record = RadiosondeProfile.objects.get(pk=profile_id)
    except RadiosondeProfile.DoesNotExist as exc:
        raise RadiosondeSourceError(
            f"No existe un radiosondeo con profile_id={profile_id}."
        ) from exc

    try:
        response = get_r2_client().get_object(
            Bucket=record.bucket,
            Key=record.object_key,
        )
    except ClientError as exc:
        error = exc.response.get("Error", {})
        code = error.get("Code", "Unknown")
        raise RadiosondeSourceError(
            f"R2 rechazó la lectura de {record.object_key}: {code}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeSourceError(
            f"No se pudo conectar con R2 para leer {record.object_key}."
        ) from exc

    declared_size = response.get("ContentLength")
    if declared_size is not None and declared_size > MAX_RADIOSONDE_BYTES:
        raise RadiosondeSourceError(
            f"El objeto supera el límite de {MAX_RADIOSONDE_BYTES} bytes."
        )

    body = response["Body"]
    try:
        raw_bytes = body.read(MAX_RADIOSONDE_BYTES + 1)
    finally:
        body.close()

    if len(raw_bytes) > MAX_RADIOSONDE_BYTES:
        raise RadiosondeSourceError(
            f"El objeto supera el límite de {MAX_RADIOSONDE_BYTES} bytes."
        )

    text = raw_bytes.decode("utf-8", errors="replace")
    dataframe = _read_edt_dataframe(text)
    station, launch_time = _read_header_metadata(text)

    return LoadedRadiosondeSource(
        record=record,
        raw_bytes=raw_bytes,
        dataframe=dataframe,
        station=station,
        launch_time=launch_time,
        etag=(response.get("ETag") or "").strip('"') or None,
    )


def inspect_radiosonde_source(profile_id: int) -> dict:
    """Devuelve metadatos seguros para comprobar el objeto recuperado."""
    return load_radiosonde_source(profile_id).inspection()


def _read_edt_dataframe(text: str) -> pd.DataFrame:
    lines = text.splitlines()
    header_index = None

    for index, line in enumerate(lines):
        columns = set(line.split())
        if REQUIRED_COLUMNS.issubset(columns):
            header_index = index
            break

    if header_index is None:
        raise RadiosondeSourceError(
            "El objeto no contiene un encabezado EDT reconocible."
        )

    dataframe = pd.read_csv(
        StringIO(text),
        sep=r"\s+",
        skiprows=header_index,
        engine="python",
    )
    dataframe.columns = dataframe.columns.str.strip()
    missing = REQUIRED_COLUMNS.difference(dataframe.columns)
    if missing:
        raise RadiosondeSourceError(
            f"Faltan columnas requeridas en el TSV: {', '.join(sorted(missing))}."
        )

    return dataframe.dropna(how="all").reset_index(drop=True)


def _read_header_metadata(text: str) -> tuple[str | None, datetime | None]:
    station_match = re.search(r"^Station:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    launch_match = re.search(
        r"^Launch time:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC\s*$",
        text,
        flags=re.MULTILINE,
    )

    station = station_match.group(1) if station_match else None
    launch_time = None
    if launch_match:
        launch_time = datetime.strptime(
            launch_match.group(1), "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)

    return station, launch_time


def _datetime_to_iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _matches_synoptic_time(launch_time: datetime, catalog_time) -> bool:
    """Compara la hora real con el ciclo nominal, tolerando lanzamientos cercanos."""
    launch_minutes = launch_time.hour * 60 + launch_time.minute
    catalog_minutes = catalog_time.hour * 60 + catalog_time.minute
    difference = abs(launch_minutes - catalog_minutes)
    circular_difference = min(difference, 24 * 60 - difference)
    return circular_difference <= SYNOPTIC_TIME_TOLERANCE_MINUTES
