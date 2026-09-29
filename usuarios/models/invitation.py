from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

from .role import PersonRole


class InvitationQuerySet(models.QuerySet):
    def delete(self):
        if self.exclude(status="PENDING").exists():
            raise ValueError("Only pending invitations can be cancelled.")

        now = timezone.now()
        count = self.update(
            status="CANCELLED",
            cancelled_at=now,
            updated_at=now,
        )
        return count, {"usuarios.Invitation": count}


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CANCELLED = "CANCELLED", "Cancelled"
        ACCEPTED = "ACCEPTED", "Accepted"
        EXPIRED = "EXPIRED", "Expired"

    email = models.EmailField()
    person_role = models.ForeignKey(
        PersonRole,
        on_delete=models.PROTECT,
        related_name="invitations",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_invitations",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    accepted_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_invitation",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        db_table = "invitations"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "expires_at"],
                name="invitation_status_expiry_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=Q(status="PENDING"),
                name="one_pending_invitation_per_email",
            ),
            models.CheckConstraint(
                condition=~Q(email=""),
                name="invitation_email_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="invitation_expiry_after_creation",
            ),
            models.CheckConstraint(
                condition=Q(
                    status="ACCEPTED",
                    accepted_at__isnull=False,
                    accepted_user__isnull=False,
                    cancelled_at__isnull=True,
                )
                | Q(
                    status="CANCELLED",
                    accepted_at__isnull=True,
                    accepted_user__isnull=True,
                    cancelled_at__isnull=False,
                )
                | Q(
                    status__in=["PENDING", "EXPIRED"],
                    accepted_at__isnull=True,
                    accepted_user__isnull=True,
                    cancelled_at__isnull=True,
                ),
                name="invitation_status_dates_consistent",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().casefold()
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        result = type(self).objects.filter(pk=self.pk).delete()
        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        return result

    def __str__(self):
        return f"{self.email} ({self.status})"
