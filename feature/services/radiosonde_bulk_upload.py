"""Carga independiente de los TSV de una carpeta anual."""

import logging
import re

from feature.models import RadiosondeProfile
from .radiosonde_upload import (
    RADIOSONDE_BUCKET,
    RadiosondeUploadConflictError,
    RadiosondeUploadDuplicateError,
    RadiosondeUploadError,
    RadiosondeUploadStorageError,
    upload_radiosonde_tsv,
)


MAX_BULK_FILES = 50
MAX_BULK_BYTES = 50 * 1024 * 1024
logger = logging.getLogger(__name__)


def upload_radiosonde_folder(year, files):
    """Cada archivo conserva la transacción y validación de la carga individual."""
    results = []
    for uploaded_file in files:
        filename = re.split(r"[\\/]", uploaded_file.name)[-1]
        item = {"filename": filename, "object_key": f"{year}/{filename}"}
        try:
            result = upload_radiosonde_tsv(
                uploaded_file, year=year, check_duplicate_content=True,
            )
            item.update({
                "status": "uploaded", "profile": result["profile"],
                "storage": result["storage"], "warnings": result["warnings"],
            })
        except RadiosondeUploadDuplicateError as exc:
            item.update({
                "status": "skipped", "reason": "duplicate_content",
                "detail": str(exc), "existing_profile_id": exc.record.pk,
                "existing_object_key": exc.record.object_key,
            })
        except RadiosondeUploadConflictError as exc:
            record = RadiosondeProfile.objects.filter(object_key=item["object_key"]).first()
            item.update({
                "status": "skipped" if record is not None else "failed",
                "reason": "already_registered" if record is not None else "storage_object_without_catalog",
                "detail": str(exc),
            })
            if record is not None:
                item["existing_profile_id"] = record.pk
        except RadiosondeUploadStorageError as exc:
            item.update({"status": "failed", "reason": "storage_error", "detail": str(exc)})
        except RadiosondeUploadError as exc:
            item.update({"status": "failed", "reason": "invalid_file", "detail": str(exc)})
        except Exception:
            logger.exception("Error cargando el TSV %s de la carpeta %s", filename, year)
            item.update({
                "status": "failed", "reason": "processing_error",
                "detail": "No se pudo procesar este archivo.",
            })
        results.append(item)
    counts = {name: sum(item["status"] == name for item in results) for name in ("uploaded", "skipped", "failed")}
    return {
        "year": year, "bucket": RADIOSONDE_BUCKET, "prefix": f"{year}/",
        "status": "completed_with_errors" if counts["failed"] else "completed",
        "total": len(results), **counts, "results": results,
    }
