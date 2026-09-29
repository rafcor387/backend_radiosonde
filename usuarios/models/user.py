from django.apps import apps
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .role import UserRole


class UserQuerySet(models.QuerySet):
    def delete(self):
        now = timezone.now()
        person_ids = list(self.values_list("person_id", flat=True))
        if not person_ids:
            return 0, {}

        Person = apps.get_model("usuarios", "Person")
        with transaction.atomic():
            count = self.update(
                is_active=False,
                deleted_at=now,
                updated_at=now,
            )
            Person.objects.filter(id__in=person_ids).update(
                deleted_at=now,
                updated_at=now,
            )

        return count, {"usuarios.User": count}


class CustomUserManager(BaseUserManager.from_queryset(UserQuerySet)):
    def get_by_natural_key(self, username):
        return self.get(username__iexact=username)

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("The username field is required.")
        if not extra_fields.get("person"):
            raise ValueError("The person field is required.")
        if not extra_fields.get("user_role"):
            raise ValueError("The user_role field is required.")

        user = self.model(
            username=username.strip().upper(),
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")

        extra_fields.setdefault(
            "user_role",
            UserRole.objects.get(code="ADMINISTRATOR"),
        )
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=20, unique=True)
    person = models.OneToOneField(
        "Person",
        on_delete=models.PROTECT,
        related_name="user",
    )
    user_role = models.ForeignKey(
        UserRole,
        on_delete=models.PROTECT,
        related_name="users",
    )
    token_version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True, db_index=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["person", "user_role"]

    class Meta:
        db_table = "users"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                Lower("username"),
                name="user_username_case_insensitive_unique",
            ),
            models.CheckConstraint(
                condition=~Q(username=""),
                name="user_username_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(token_version__gte=1),
                name="user_token_version_positive",
            ),
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True) | Q(is_active=False),
                name="deleted_user_must_be_inactive",
            ),
        ]

    def save(self, *args, **kwargs):
        self.username = self.username.strip().upper()
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        result = type(self).objects.filter(pk=self.pk).delete()
        self.is_active = False
        self.deleted_at = timezone.now()
        return result

    def __str__(self):
        return self.username
