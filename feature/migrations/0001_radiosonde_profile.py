import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RadiosondeProfile",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("date", models.DateField(db_index=True)),
                ("time", models.TimeField(blank=True, null=True)),
                ("observed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
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
