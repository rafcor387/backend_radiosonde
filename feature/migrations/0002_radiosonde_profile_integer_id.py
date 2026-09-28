from django.db import migrations, models


def ensure_radiosonde_profile_is_empty(apps, schema_editor):
    """Evita perder registros al reemplazar la clave primaria UUID."""
    RadiosondeProfile = apps.get_model("feature", "RadiosondeProfile")
    if RadiosondeProfile.objects.exists():
        raise RuntimeError(
            "No se puede cambiar el id UUID a un id incremental porque "
            "radiosonde_profile ya contiene registros."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("feature", "0001_radiosonde_profile"),
    ]

    operations = [
        migrations.RunPython(
            ensure_radiosonde_profile_is_empty,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.DeleteModel(
            name="RadiosondeProfile",
        ),
        migrations.CreateModel(
            name="RadiosondeProfile",
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
                ("date", models.DateField(db_index=True)),
                ("time", models.TimeField(blank=True, null=True)),
                (
                    "observed_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("bucket", models.CharField(max_length=255)),
                ("object_key", models.CharField(max_length=1024, unique=True)),
            ],
            options={
                "db_table": "radiosonde_profile",
                "ordering": ("date", "time", "observed_at"),
                "indexes": [
                    models.Index(
                        fields=["date", "time"],
                        name="radio_date_time_idx",
                    )
                ],
            },
        ),
    ]
