from django.db import models


class RadiosondeProfile(models.Model):
    """Catálogo de archivos de radiosondeo almacenados en Cloudflare R2."""

    date = models.DateField(db_index=True)
    time = models.TimeField(null=True, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    bucket = models.CharField(max_length=255)
    object_key = models.CharField(max_length=1024, unique=True)

    class Meta:
        db_table = "radiosonde_profile"
        ordering = ("date", "time", "observed_at")
        indexes = [
            models.Index(fields=("date", "time"), name="radio_date_time_idx"),
        ]

    def __str__(self):
        return f"LPZ {self.observed_at or self.date}"


class RadiosondeReport(models.Model):
    """Estado y ubicación de un informe PDF derivado de varios perfiles."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        PROCESSING = "processing", "Procesando"
        READY = "ready", "Listo"
        FAILED = "failed", "Fallido"

    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    time = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    fingerprint = models.CharField(max_length=64, db_index=True)
    report_version = models.CharField(max_length=16)
    bucket = models.CharField(max_length=255)
    object_key = models.CharField(max_length=1024, null=True, blank=True)
    filename = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    profile_count = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "radiosonde_report"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("fingerprint", "status"),
                name="radio_report_cache_idx",
            ),
        ]

    def __str__(self):
        return f"Informe LPZ {self.start_date} a {self.end_date} ({self.status})"
