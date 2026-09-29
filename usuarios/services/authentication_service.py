from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone

from usuarios.exceptions import InvalidCredentialsError
from usuarios.models import User
from usuarios.services.access_token_service import AccessTokenService


class AuthenticationService:
    @staticmethod
    def login(username, password):
        normalized_username = username.strip().upper()
        user = authenticate(username=normalized_username, password=password)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise InvalidCredentialsError()

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return {
            "user": user,
            "access": AccessTokenService.create_for_user(user),
            "expires_in": AccessTokenService.lifetime_seconds(),
        }

    @staticmethod
    @transaction.atomic
    def logout(user):
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        locked_user.token_version += 1
        locked_user.updated_at = timezone.now()
        locked_user.save(update_fields=["token_version", "updated_at"])
