import django.db.models.functions.text
from django.db import migrations, models


USER_ROLE_NAMES = {
    "ADMINISTRATOR": "Administrador",
    "USER": "Usuario",
}

PERSON_ROLE_NAMES = {
    "STUDENT": "Estudiante",
    "INTERN": "Pasante",
    "TEACHER": "Docente",
    "ASSISTANT": "Auxiliar",
}

INVITATION_STATUSES = {
    "PENDING": "PENDIENTE",
    "CANCELLED": "CANCELADA",
    "ACCEPTED": "ACEPTADA",
    "EXPIRED": "EXPIRADA",
}


def translate_values(apps, schema_editor):
    UserRole = apps.get_model("usuarios", "UserRole")
    PersonRole = apps.get_model("usuarios", "PersonRole")
    Invitation = apps.get_model("usuarios", "Invitation")

    for code, name in USER_ROLE_NAMES.items():
        UserRole.objects.filter(code=code).update(name=name)

    for code, name in PERSON_ROLE_NAMES.items():
        PersonRole.objects.filter(code=code).update(name=name)

    for old_status, new_status in INVITATION_STATUSES.items():
        Invitation.objects.filter(status=old_status).update(status=new_status)


def restore_values(apps, schema_editor):
    UserRole = apps.get_model("usuarios", "UserRole")
    PersonRole = apps.get_model("usuarios", "PersonRole")
    Invitation = apps.get_model("usuarios", "Invitation")

    english_user_names = {
        "ADMINISTRATOR": "Administrator",
        "USER": "User",
    }
    english_person_names = {
        "STUDENT": "Student",
        "INTERN": "Intern",
        "TEACHER": "Teacher",
        "ASSISTANT": "Assistant",
    }

    for code, name in english_user_names.items():
        UserRole.objects.filter(code=code).update(name=name)

    for code, name in english_person_names.items():
        PersonRole.objects.filter(code=code).update(name=name)

    for old_status, new_status in INVITATION_STATUSES.items():
        Invitation.objects.filter(status=new_status).update(status=old_status)


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0002_seed_roles"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="invitation",
            name="one_pending_invitation_per_email",
        ),
        migrations.RemoveConstraint(
            model_name="invitation",
            name="invitation_status_dates_consistent",
        ),
        migrations.RunPython(translate_values, restore_values),
        migrations.AlterField(
            model_name="userrole",
            name="code",
            field=models.CharField(
                choices=[
                    ("ADMINISTRATOR", "Administrador"),
                    ("USER", "Usuario"),
                ],
                max_length=30,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="personrole",
            name="code",
            field=models.CharField(
                choices=[
                    ("STUDENT", "Estudiante"),
                    ("INTERN", "Pasante"),
                    ("TEACHER", "Docente"),
                    ("ASSISTANT", "Auxiliar"),
                ],
                max_length=30,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="invitation",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDIENTE", "Pendiente"),
                    ("CANCELADA", "Cancelada"),
                    ("ACEPTADA", "Aceptada"),
                    ("EXPIRADA", "Expirada"),
                ],
                default="PENDIENTE",
                max_length=15,
            ),
        ),
        migrations.AddConstraint(
            model_name="invitation",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                condition=models.Q(("status", "PENDIENTE")),
                name="one_pending_invitation_per_email",
            ),
        ),
        migrations.AddConstraint(
            model_name="invitation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("accepted_at__isnull", False),
                        ("accepted_user__isnull", False),
                        ("cancelled_at__isnull", True),
                        ("status", "ACEPTADA"),
                    ),
                    models.Q(
                        ("accepted_at__isnull", True),
                        ("accepted_user__isnull", True),
                        ("cancelled_at__isnull", False),
                        ("status", "CANCELADA"),
                    ),
                    models.Q(
                        ("accepted_at__isnull", True),
                        ("accepted_user__isnull", True),
                        ("cancelled_at__isnull", True),
                        ("status__in", ["PENDIENTE", "EXPIRADA"]),
                    ),
                    _connector="OR",
                ),
                name="invitation_status_dates_consistent",
            ),
        ),
    ]
