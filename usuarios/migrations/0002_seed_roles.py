from django.db import migrations


USER_ROLES = (
    ("ADMINISTRATOR", "Administrator"),
    ("USER", "User"),
)

PERSON_ROLES = (
    ("STUDENT", "Student"),
    ("INTERN", "Intern"),
    ("TEACHER", "Teacher"),
    ("ASSISTANT", "Assistant"),
)


def seed_roles(apps, schema_editor):
    UserRole = apps.get_model("usuarios", "UserRole")
    PersonRole = apps.get_model("usuarios", "PersonRole")

    for code, name in USER_ROLES:
        UserRole.objects.update_or_create(code=code, defaults={"name": name})

    for code, name in PERSON_ROLES:
        PersonRole.objects.update_or_create(code=code, defaults={"name": name})


def remove_seeded_roles(apps, schema_editor):
    UserRole = apps.get_model("usuarios", "UserRole")
    PersonRole = apps.get_model("usuarios", "PersonRole")

    UserRole.objects.filter(code__in=[code for code, _ in USER_ROLES]).delete()
    PersonRole.objects.filter(code__in=[code for code, _ in PERSON_ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, remove_seeded_roles),
    ]
