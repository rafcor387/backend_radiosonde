from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("feature", "0002_radiosonde_profile_integer_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="RadiosondeReport",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("start_date", models.DateField(db_index=True)),
                ("end_date", models.DateField(db_index=True)),
                ("time", models.TimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("processing", "Procesando"),
                            ("ready", "Listo"),
                            ("failed", "Fallido"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("fingerprint", models.CharField(db_index=True, max_length=64)),
                ("report_version", models.CharField(max_length=16)),
                ("bucket", models.CharField(max_length=255)),
                ("object_key", models.CharField(blank=True, max_length=1024, null=True)),
                ("filename", models.CharField(max_length=255)),
                ("size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("profile_count", models.PositiveIntegerField(default=0)),
                ("processed_count", models.PositiveIntegerField(default=0)),
                ("failed_count", models.PositiveIntegerField(default=0)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "radiosonde_report",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["fingerprint", "status"],
                        name="radio_report_cache_idx",
                    )
                ],
            },
        ),
    ]
