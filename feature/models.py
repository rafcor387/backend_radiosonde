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
