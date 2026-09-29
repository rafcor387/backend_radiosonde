from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class VersionedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        token_version = validated_token.get("token_version")

        if (
            token_version is None
            or token_version != user.token_version
            or user.deleted_at is not None
        ):
            raise AuthenticationFailed(
                "The access token has been invalidated.",
                code="token_invalidated",
            )

        return user


class VersionedJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "usuarios.authentication.VersionedJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
