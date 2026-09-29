from datetime import time
import hashlib
import re

from botocore.exceptions import BotoCoreError, ClientError
from django.db import IntegrityError, transaction

from feature.models import RadiosondeProfile

from .r2_client import get_r2_client
from .radiosonde_source import (
    LoadedRadiosondeSource,
    MAX_RADIOSONDE_BYTES,
    RadiosondeSourceError,
    parse_radiosonde_bytes,
)


RADIOSONDE_BUCKET = "radiosondes"
SYNOPTIC_HOURS = (0, 12)
SYNOPTIC_TOLERANCE_MINUTES = 60


class RadiosondeUploadError(Exception):
    """Error controlado al validar o almacenar un TSV."""


class RadiosondeUploadConflictError(RadiosondeUploadError):
    """El nombre del objeto ya está registrado o almacenado."""


class RadiosondeUploadStorageError(RadiosondeUploadError):
    """R2 no pudo completar una operación del alta."""


def upload_radiosonde_tsv(uploaded_file) -> dict:
    """Valida un TSV, lo almacena en R2 y crea su registro de catálogo."""
    object_key = _object_key(uploaded_file)
    raw_bytes = uploaded_file.read(MAX_RADIOSONDE_BYTES + 1)
    if len(raw_bytes) > MAX_RADIOSONDE_BYTES:
        raise RadiosondeUploadError(
            f"El archivo supera el límite de {MAX_RADIOSONDE_BYTES} bytes."
        )

    try:
        parsed = parse_radiosonde_bytes(raw_bytes)
    except RadiosondeSourceError as exc:
        raise RadiosondeUploadError(str(exc)) from exc

    _validate_metadata(parsed.station, parsed.launch_time)
    launch_time = parsed.launch_time
    synoptic_time = _infer_synoptic_time(launch_time)
    warnings = []
    if synoptic_time is None:
        warnings.append(
            "La hora de lanzamiento no está a menos de 60 minutos de 00:00Z "
            "o 12:00Z; time se guardó como null."
        )

    if RadiosondeProfile.objects.filter(object_key=object_key).exists():
        raise RadiosondeUploadConflictError(
            f"Ya existe un radiosondeo con object_key={object_key}."
        )

    client = get_r2_client()
    if _object_exists(client, object_key):
        raise RadiosondeUploadConflictError(
            f"El objeto {object_key} ya existe en R2 y no será sobrescrito."
        )

    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    uploaded = False
    record = None
    etag = None
    try:
        with transaction.atomic():
            record = RadiosondeProfile.objects.create(
                date=launch_time.date(),
                time=synoptic_time,
                observed_at=launch_time,
                bucket=RADIOSONDE_BUCKET,
                object_key=object_key,
            )
            response = client.put_object(
                Bucket=RADIOSONDE_BUCKET,
                Key=object_key,
                Body=raw_bytes,
                ContentType="text/tab-separated-values; charset=utf-8",
                Metadata={
                    "profile-id": str(record.pk),
                    "source-sha256": source_hash,
                    "observed-at": launch_time.isoformat(),
                },
            )
            uploaded = True
            etag = (response.get("ETag") or "").strip('"') or None
    except IntegrityError as exc:
        if uploaded:
            _delete_uploaded_object(client, object_key)
        raise RadiosondeUploadConflictError(
            f"Ya existe un radiosondeo con object_key={object_key}."
        ) from exc
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise RadiosondeUploadStorageError(
            f"R2 rechazó la carga de {object_key}: {code}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeUploadStorageError(
            f"No se pudo conectar con R2 para cargar {object_key}."
        ) from exc
    except Exception:
        if uploaded:
            _delete_uploaded_object(client, object_key)
        raise

    loaded = LoadedRadiosondeSource(
        record=record,
        raw_bytes=raw_bytes,
        dataframe=parsed.dataframe,
        station=parsed.station,
        launch_time=launch_time,
        etag=etag,
    )
    result = loaded.inspection()
    result["created"] = True
    result["warnings"] = warnings + result["warnings"]
    return result


def _object_key(uploaded_file) -> str:
    original_name = str(getattr(uploaded_file, "name", "") or "").strip()
    filename = re.split(r"[\\/]", original_name)[-1]
    if (
        not filename
        or filename in {".", ".."}
        or len(filename) > 255
        or not filename.lower().endswith(".tsv")
        or any(ord(character) < 32 for character in filename)
    ):
        raise RadiosondeUploadError(
            "El archivo debe tener un nombre TSV válido de hasta 255 caracteres."
        )
    return filename


def _validate_metadata(station, launch_time) -> None:
    if not station:
        raise RadiosondeUploadError(
            "El TSV no contiene el campo Station requerido."
        )
    canonical_station = re.sub(r"[^a-z0-9]", "", station.casefold())
    if "lapaz" not in canonical_station and "85201" not in canonical_station:
        raise RadiosondeUploadError(
            f"El TSV pertenece a una estación distinta de La Paz: {station}."
        )
    if launch_time is None:
        raise RadiosondeUploadError(
            "El TSV no contiene un Launch time UTC válido."
        )


def _infer_synoptic_time(launch_time):
    launch_minutes = launch_time.hour * 60 + launch_time.minute
    candidates = []
    for hour in SYNOPTIC_HOURS:
        nominal_minutes = hour * 60
        difference = abs(launch_minutes - nominal_minutes)
        difference = min(difference, 24 * 60 - difference)
        candidates.append((difference, hour))
    difference, hour = min(candidates)
    if difference > SYNOPTIC_TOLERANCE_MINUTES:
        return None
    return time(hour, 0)


def _object_exists(client, object_key: str) -> bool:
    try:
        client.head_object(Bucket=RADIOSONDE_BUCKET, Key=object_key)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
            return False
        raise RadiosondeUploadStorageError(
            f"R2 rechazó la comprobación de {object_key}: {code or 'Unknown'}."
        ) from exc
    except BotoCoreError as exc:
        raise RadiosondeUploadStorageError(
            f"No se pudo consultar R2 antes de cargar {object_key}."
        ) from exc


def _delete_uploaded_object(client, object_key: str) -> None:
    try:
        client.delete_object(Bucket=RADIOSONDE_BUCKET, Key=object_key)
    except (ClientError, BotoCoreError) as exc:
        raise RadiosondeUploadStorageError(
            f"La base de datos rechazó el alta y no se pudo retirar {object_key} de R2."
        ) from exc
