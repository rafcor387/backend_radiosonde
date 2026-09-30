from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from usuarios.error_codes import ErrorCode
from usuarios.exceptions import ServiceError
from usuarios.models import Invitation, Person, PersonRole, User, UserRole
from usuarios.services.invitation_email_service import InvitationEmailService
from usuarios.services.invitation_token_service import InvitationTokenService
from usuarios.services.password_service import PasswordService
from usuarios.services.username_service import (
    UsernameGenerationError,
    UsernameService,
)


class InvitationService:
    @staticmethod
    @transaction.atomic
    def list_all():
        now = timezone.now()
        Invitation.objects.filter(
            status=Invitation.Status.PENDING,
            expires_at__lte=now,
        ).update(
            status=Invitation.Status.EXPIRED,
            updated_at=now,
        )
        return Invitation.objects.select_related(
            "person_role",
            "invited_by",
            "invited_by__person",
        ).order_by("-created_at", "-id")

    @staticmethod
    def cancel(*, invitation_id):
        invitation = None
        cancelled = False

        with transaction.atomic():
            invitation = (
                Invitation.objects.select_for_update()
                .filter(pk=invitation_id)
                .first()
            )
            now = timezone.now()

            if (
                invitation is not None
                and invitation.status == Invitation.Status.PENDING
                and invitation.expires_at <= now
            ):
                invitation.status = Invitation.Status.EXPIRED
                invitation.save(update_fields=["status", "updated_at"])
            elif (
                invitation is not None
                and invitation.status == Invitation.Status.PENDING
            ):
                invitation.status = Invitation.Status.CANCELLED
                invitation.cancelled_at = now
                invitation.save(
                    update_fields=["status", "cancelled_at", "updated_at"]
                )
                cancelled = True

        if invitation is None:
            raise ServiceError(
                ErrorCode.INVITATION_NOT_FOUND,
                "La invitación solicitada no existe.",
                404,
            )
        if cancelled:
            return invitation
        if invitation.status == Invitation.Status.EXPIRED:
            raise ServiceError(
                ErrorCode.INVITATION_EXPIRED,
                "La invitación ha vencido y no puede cancelarse.",
                410,
            )
        if invitation.status == Invitation.Status.CANCELLED:
            raise ServiceError(
                ErrorCode.INVITATION_ALREADY_CANCELLED,
                "La invitación ya fue cancelada.",
                409,
            )
        if invitation.status == Invitation.Status.ACCEPTED:
            raise ServiceError(
                ErrorCode.INVITATION_ALREADY_ACCEPTED,
                "La invitación ya fue aceptada y no puede cancelarse.",
                409,
            )

        return invitation

    @staticmethod
    @transaction.atomic
    def create_and_send(*, email, person_role_code, invited_by):
        normalized_email = email.strip().casefold()
        now = timezone.now()

        if Person.objects.filter(email__iexact=normalized_email).exists():
            raise ServiceError(
                ErrorCode.INVITATION_EMAIL_ALREADY_REGISTERED,
                "Ya existe una persona registrada con este correo electrónico.",
                409,
            )

        pending = (
            Invitation.objects.select_for_update()
            .filter(
                email__iexact=normalized_email,
                status=Invitation.Status.PENDING,
            )
            .first()
        )
        if pending is not None:
            if pending.expires_at <= now:
                pending.status = Invitation.Status.EXPIRED
                pending.save(update_fields=["status", "updated_at"])
            else:
                raise ServiceError(
                    ErrorCode.INVITATION_ALREADY_PENDING,
                    "Ya existe una invitación pendiente para este correo electrónico.",
                    409,
                )

        try:
            person_role = PersonRole.objects.get(code=person_role_code)
        except PersonRole.DoesNotExist as exc:
            raise ServiceError(
                ErrorCode.VALIDATION_ERROR,
                "El rol de persona seleccionado no existe.",
                400,
                {
                    "person_role_code": [
                        {
                            "code": "invalid_choice",
                            "message": "El rol de persona seleccionado no existe.",
                        }
                    ]
                },
            ) from exc

        raw_token, token_hash = InvitationTokenService.create()
        try:
            with transaction.atomic():
                invitation = Invitation.objects.create(
                    email=normalized_email,
                    person_role=person_role,
                    invited_by=invited_by,
                    token_hash=token_hash,
                    expires_at=now
                    + timedelta(hours=settings.INVITATION_EXPIRATION_HOURS),
                )
        except IntegrityError as exc:
            if Invitation.objects.filter(
                email__iexact=normalized_email,
                status=Invitation.Status.PENDING,
            ).exists():
                raise ServiceError(
                    ErrorCode.INVITATION_ALREADY_PENDING,
                    "Ya existe una invitación pendiente para este correo electrónico.",
                    409,
                ) from exc
            raise

        try:
            InvitationEmailService.send_invitation(invitation, raw_token)
        except Exception as exc:
            raise ServiceError(
                ErrorCode.INVITATION_EMAIL_DELIVERY_FAILED,
                "No fue posible enviar el correo de invitación.",
                503,
            ) from exc

        return invitation

    @staticmethod
    def validate_token(*, raw_token):
        token_hash = InvitationTokenService.hash(raw_token.strip())

        with transaction.atomic():
            invitation = (
                Invitation.objects.select_for_update()
                .select_related("person_role")
                .filter(token_hash=token_hash)
                .first()
            )
            if (
                invitation is not None
                and invitation.status == Invitation.Status.PENDING
                and invitation.expires_at <= timezone.now()
            ):
                invitation.status = Invitation.Status.EXPIRED
                invitation.save(update_fields=["status", "updated_at"])

        InvitationService._ensure_pending(invitation)
        return invitation

    @staticmethod
    def accept(
        *,
        raw_token,
        name,
        paternal_surname,
        maternal_surname,
        password,
    ):
        token_hash = InvitationTokenService.hash(raw_token.strip())
        created_user = None

        with transaction.atomic():
            invitation = (
                Invitation.objects.select_for_update()
                .select_related("person_role")
                .filter(token_hash=token_hash)
                .first()
            )
            now = timezone.now()
            if (
                invitation is not None
                and invitation.status == Invitation.Status.PENDING
                and invitation.expires_at <= now
            ):
                invitation.status = Invitation.Status.EXPIRED
                invitation.save(update_fields=["status", "updated_at"])

            if (
                invitation is not None
                and invitation.status == Invitation.Status.PENDING
            ):
                if Person.objects.filter(
                    email__iexact=invitation.email
                ).exists():
                    raise ServiceError(
                        ErrorCode.INVITATION_EMAIL_ALREADY_REGISTERED,
                        "Ya existe una persona registrada con este correo electrónico.",
                        409,
                    )

                try:
                    username = UsernameService.generate(
                        name,
                        paternal_surname,
                        maternal_surname,
                    )
                except UsernameGenerationError as exc:
                    raise ServiceError(
                        ErrorCode.VALIDATION_ERROR,
                        "No fue posible generar un nombre de usuario válido.",
                        400,
                    ) from exc

                candidate_user = User(username=username)
                PasswordService.validate_new_password(
                    candidate_user,
                    password,
                    field_name="password",
                )
                user_role = UserRole.objects.get(code=UserRole.Code.USER)

                try:
                    with transaction.atomic():
                        person = Person.objects.create(
                            name=name.strip(),
                            paternal_surname=paternal_surname.strip(),
                            maternal_surname=maternal_surname.strip(),
                            email=invitation.email,
                            person_role=invitation.person_role,
                        )
                        created_user = User.objects.create_user(
                            username=username,
                            password=password,
                            person=person,
                            user_role=user_role,
                            is_active=True,
                            is_staff=False,
                            is_superuser=False,
                        )
                except IntegrityError as exc:
                    if Person.objects.filter(
                        email__iexact=invitation.email
                    ).exists():
                        raise ServiceError(
                            ErrorCode.INVITATION_EMAIL_ALREADY_REGISTERED,
                            (
                                "Ya existe una persona registrada con este "
                                "correo electrónico."
                            ),
                            409,
                        ) from exc
                    raise

                invitation.status = Invitation.Status.ACCEPTED
                invitation.accepted_at = now
                invitation.accepted_user = created_user
                invitation.save(
                    update_fields=[
                        "status",
                        "accepted_at",
                        "accepted_user",
                        "updated_at",
                    ]
                )

        if created_user is None:
            InvitationService._ensure_pending(invitation)

        return created_user

    @staticmethod
    def _ensure_pending(invitation):
        if invitation is None:
            raise ServiceError(
                ErrorCode.INVITATION_TOKEN_INVALID,
                "El token de invitación no es válido.",
                404,
            )
        if invitation.status == Invitation.Status.EXPIRED:
            raise ServiceError(
                ErrorCode.INVITATION_EXPIRED,
                "La invitación ha vencido.",
                410,
            )
        if invitation.status == Invitation.Status.CANCELLED:
            raise ServiceError(
                ErrorCode.INVITATION_CANCELLED,
                "La invitación fue cancelada.",
                410,
            )
        if invitation.status == Invitation.Status.ACCEPTED:
            raise ServiceError(
                ErrorCode.INVITATION_ALREADY_ACCEPTED,
                "La invitación ya fue aceptada.",
                409,
            )

