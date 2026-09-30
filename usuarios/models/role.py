from django.db import models
from django.db.models.deletion import ProtectedError
from django.db.models import Q


class FixedRoleQuerySet(models.QuerySet):
    def delete(self):
        roles = list(self)
        raise ProtectedError("Fixed roles cannot be deleted.", roles)


class UserRole(models.Model):
    class Code(models.TextChoices):
        ADMINISTRATOR = "ADMINISTRATOR", "Administrador"
        USER = "USER", "Usuario"

    code = models.CharField(max_length=30, choices=Code.choices, unique=True)
    name = models.CharField(max_length=50, unique=True)

    objects = FixedRoleQuerySet.as_manager()

    class Meta:
        db_table = "user_roles"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(code__in=["ADMINISTRATOR", "USER"]),
                name="user_role_code_valid",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="user_role_name_not_empty",
            ),
        ]

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        raise ProtectedError("Fixed roles cannot be deleted.", [self])


class PersonRole(models.Model):
    class Code(models.TextChoices):
        STUDENT = "STUDENT", "Estudiante"
        INTERN = "INTERN", "Pasante"
        TEACHER = "TEACHER", "Docente"
        ASSISTANT = "ASSISTANT", "Auxiliar"

    code = models.CharField(max_length=30, choices=Code.choices, unique=True)
    name = models.CharField(max_length=50, unique=True)

    objects = FixedRoleQuerySet.as_manager()

    class Meta:
        db_table = "person_roles"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    code__in=["STUDENT", "INTERN", "TEACHER", "ASSISTANT"]
                ),
                name="person_role_code_valid",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="person_role_name_not_empty",
            ),
        ]

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        raise ProtectedError("Fixed roles cannot be deleted.", [self])
