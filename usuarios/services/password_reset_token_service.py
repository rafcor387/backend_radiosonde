from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing

from usuarios.models import User


class PasswordResetTokenInvalid(Exception):
    pass


class PasswordResetTokenExpired(Exception):
    pass


class PasswordResetTokenService:
    salt = "usuarios.password-reset"

    @classmethod
    def create(cls, user):
        return signing.dumps(
            {
                "user_id": user.pk,
                "django_token": default_token_generator.make_token(user),
            },
            salt=cls.salt,
            compress=True,
        )

    @classmethod
    def resolve(cls, token, *, lock=False):
        try:
            payload = signing.loads(
                token,
                salt=cls.salt,
                max_age=settings.PASSWORD_RESET_TIMEOUT,
            )
        except signing.SignatureExpired as exc:
            raise PasswordResetTokenExpired from exc
        except (signing.BadSignature, TypeError, ValueError) as exc:
            raise PasswordResetTokenInvalid from exc

        user_id = payload.get("user_id") if isinstance(payload, dict) else None
        django_token = (
            payload.get("django_token") if isinstance(payload, dict) else None
        )
        if not user_id or not django_token:
            raise PasswordResetTokenInvalid

        queryset = User.objects.select_related("person")
        if lock:
            queryset = queryset.select_for_update()

        try:
            user = queryset.get(
                pk=user_id,
                is_active=True,
                deleted_at__isnull=True,
                person__deleted_at__isnull=True,
            )
        except User.DoesNotExist as exc:
            raise PasswordResetTokenInvalid from exc

        if not default_token_generator.check_token(user, django_token):
            raise PasswordResetTokenInvalid

        return user
