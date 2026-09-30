import logging

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from usuarios.error_codes import ErrorCode
from usuarios.exceptions import ServiceError
from usuarios.models import User
from usuarios.services.password_email_service import PasswordEmailService
from usuarios.services.password_reset_token_service import (
    PasswordResetTokenExpired,
    PasswordResetTokenInvalid,
    PasswordResetTokenService,
)


logger = logging.getLogger(__name__)


class PasswordService:
    forgot_response_message = (
        "Si existe una cuenta activa con ese correo electrónico, "
        "se enviaron las instrucciones para restablecer la contraseña."
    )

    @staticmethod
    @transaction.atomic
    def change_password(*, user, current_password, new_password):
        locked_user = User.objects.select_for_update().get(pk=user.pk)

        if not locked_user.check_password(current_password):
            raise ServiceError(
                ErrorCode.AUTH_CURRENT_PASSWORD_INCORRECT,
                "La contraseña actual es incorrecta.",
                400,
                {
                    "current_password": [
                        {
                            "code": "incorrect",
                            "message": "La contraseña actual es incorrecta.",
                        }
                    ]
                },
            )

        PasswordService.validate_new_password(locked_user, new_password)
        PasswordService._save_password(locked_user, new_password)

    @staticmethod
    def request_reset(*, email):
        user = (
            User.objects.select_related("person")
            .filter(
                person__email__iexact=email.strip().casefold(),
                person__deleted_at__isnull=True,
                is_active=True,
                deleted_at__isnull=True,
            )
            .first()
        )
        if user is None:
            return

        token = PasswordResetTokenService.create(user)
        try:
            PasswordEmailService.send_reset_email(user, token)
        except Exception:
            # La respuesta pública debe ser idéntica exista o no el correo.
            logger.exception("Password reset email delivery failed")

    @staticmethod
    @transaction.atomic
    def confirm_reset(*, token, new_password):
        try:
            user = PasswordResetTokenService.resolve(token, lock=True)
        except PasswordResetTokenExpired as exc:
            raise ServiceError(
                ErrorCode.PASSWORD_RESET_TOKEN_EXPIRED,
                "El token para restablecer la contraseña ha vencido.",
                400,
            ) from exc
        except PasswordResetTokenInvalid as exc:
            raise ServiceError(
                ErrorCode.PASSWORD_RESET_TOKEN_INVALID,
                "El token para restablecer la contraseña no es válido.",
                400,
            ) from exc

        PasswordService.validate_new_password(user, new_password)
        PasswordService._save_password(user, new_password)

    @staticmethod
    def validate_new_password(user, new_password, *, field_name="new_password"):
        if user.check_password(new_password):
            raise ServiceError(
                ErrorCode.VALIDATION_ERROR,
                "La nueva contraseña no es válida.",
                400,
                {
                    field_name: [
                        {
                            "code": "password_unchanged",
                            "message": (
                                "La nueva contraseña debe ser diferente "
                                "a la contraseña actual."
                            ),
                        }
                    ]
                },
            )

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            errors = [
                {
                    "code": error.code or "invalid_password",
                    "message": error.message % (error.params or {}),
                }
                for error in exc.error_list
            ]
            raise ServiceError(
                ErrorCode.VALIDATION_ERROR,
                "La nueva contraseña no cumple los requisitos de seguridad.",
                400,
                {field_name: errors},
            ) from exc

    @staticmethod
    def _save_password(user, new_password):
        user.set_password(new_password)
        user.token_version += 1
        user.updated_at = timezone.now()
        user.save(update_fields=["password", "token_version", "updated_at"])
