from django.apps import apps
from django.db import transaction
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .role import PersonRole


class PersonQuerySet(models.QuerySet):
    def delete(self):
        now = timezone.now()
        person_ids = list(self.values_list("id", flat=True))
        if not person_ids:
            return 0, {}

        User = apps.get_model("usuarios", "User")
        with transaction.atomic():
            User.objects.filter(person_id__in=person_ids).update(
                is_active=False,
                deleted_at=now,
                updated_at=now,
            )
            count = self.update(deleted_at=now, updated_at=now)

        return count, {"usuarios.Person": count}


class Person(models.Model):
    name = models.CharField(max_length=100)
    paternal_surname = models.CharField(max_length=100)
    maternal_surname = models.CharField(max_length=100)
    email = models.EmailField()
    person_role = models.ForeignKey(
        PersonRole,
        on_delete=models.PROTECT,
        related_name="persons",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = PersonQuerySet.as_manager()

    class Meta:
        db_table = "persons"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="person_email_case_insensitive_unique",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="person_name_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(paternal_surname=""),
                name="person_paternal_surname_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(maternal_surname=""),
                name="person_maternal_surname_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(email=""),
                name="person_email_not_empty",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().casefold()
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        result = type(self).objects.filter(pk=self.pk).delete()
        self.deleted_at = timezone.now()
        return result

    def __str__(self):
        return f"{self.name} {self.paternal_surname} {self.maternal_surname}"
