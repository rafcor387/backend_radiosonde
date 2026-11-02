from datetime import time
import hashlib
import re

from botocore.exceptions import BotoCoreError, ClientError
from django.db import IntegrityError, transaction
from django.db.models import Q

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


class RadiosondeUploadDuplicateError(RadiosondeUploadConflictError):
    """El mismo contenido ya está catalogado bajo otra clave."""

    def __init__(self, record):
        super().__init__(f"El contenido ya está registrado como {record.object_key}.")
        self.record = record


def upload_radiosonde_tsv(uploaded_file, *, year=None, check_duplicate_content=False) -> dict:
    """Valida un TSV, lo almacena en R2 y crea su registro de catálogo."""
    object_key = _object_key(uploaded_file)
    raw_bytes = uploaded_file.read(MAX_RADIOSONDE_BYTES + 1)
    if len(raw_bytes) > MAX_RADIOSONDE_BYTES:
        raise RadiosondeUploadError(
            f"El archivo supera el límite de {MAX_RADIOSONDE_BYTES} bytes."
        )

    try:
        parsed = parse_radiosonde_bytes(raw_bytes)
    except (RadiosondeSourceError, ValueError) as exc:
        raise RadiosondeUploadError(str(exc)) from exc

    _validate_metadata(parsed.station, parsed.launch_time)
    launch_time = parsed.launch_time
    if year is not None:
        if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
            raise RadiosondeUploadError("El año de la carpeta no es válido.")
        if launch_time.year != year:
            raise RadiosondeUploadError(
                f"El TSV declara un lanzamiento de {launch_time.year}, "
                f"pero la carpeta corresponde a {year}."
            )
        object_key = f"{year}/{object_key}"
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

    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    client = get_r2_client()
    if check_duplicate_content:
        duplicate = _find_duplicate_profile(client, source_hash, launch_time)
        if duplicate is not None:
            raise RadiosondeUploadDuplicateError(duplicate)
    if _object_exists(client, object_key):
        raise RadiosondeUploadConflictError(
            f"El objeto {object_key} ya existe en R2 y no será sobrescrito."
        )

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


def _find_duplicate_profile(client, source_hash, launch_time):
    """Reutiliza el hash de R2; para registros antiguos compara los bytes."""
    candidates = RadiosondeProfile.objects.filter(bucket=RADIOSONDE_BUCKET).filter(
        Q(observed_at=launch_time)
        | Q(observed_at__isnull=True, date=launch_time.date())
    )
    for record in candidates.iterator():
        try:
            head = client.head_object(Bucket=record.bucket, Key=record.object_key)
            stored_hash = head.get("Metadata", {}).get("source-sha256")
            if stored_hash is None:
                response = client.get_object(Bucket=record.bucket, Key=record.object_key)
                body = response["Body"]
                try:
                    content = body.read(MAX_RADIOSONDE_BYTES + 1)
                finally:
                    body.close()
                if len(content) > MAX_RADIOSONDE_BYTES:
                    raise RadiosondeUploadStorageError(
                        f"El archivo existente {record.object_key} supera el límite de tamaño."
                    )
                stored_hash = hashlib.sha256(content).hexdigest()
            if stored_hash == source_hash:
                return record
        except (ClientError, BotoCoreError) as exc:
            raise RadiosondeUploadStorageError(
                f"No se pudo comprobar contenido duplicado para {record.object_key}."
            ) from exc
    return None


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
