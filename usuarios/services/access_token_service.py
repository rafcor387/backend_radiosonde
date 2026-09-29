from datetime import timedelta

from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken


class AccessTokenService:
    @staticmethod
    def create_for_user(user):
        token = AccessToken.for_user(user)
        token["token_version"] = user.token_version
        return str(token)

    @staticmethod
    def lifetime_seconds():
        lifetime = settings.SIMPLE_JWT.get(
            "ACCESS_TOKEN_LIFETIME",
            timedelta(hours=8),
        )
        return int(lifetime.total_seconds())
