from urllib.parse import parse_qs, unquote, urlparse

from rest_framework import serializers

from usuarios.models import Person, PersonRole, User, UserRole


def field_errors(name):
    return {
        "required": f"El campo {name} es obligatorio.",
        "blank": f"El campo {name} no puede estar vacío.",
        "null": f"El campo {name} no puede ser nulo.",
    }


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(
        max_length=20,
        trim_whitespace=True,
        error_messages=field_errors("username"),
    )
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("password"),
    )


class UserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserRole
        fields = ["id", "code", "name"]


class PersonRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonRole
        fields = ["id", "code", "name"]


class CurrentPersonSerializer(serializers.ModelSerializer):
    person_role = PersonRoleSerializer(read_only=True)

    class Meta:
        model = Person
        fields = [
            "id",
            "name",
            "paternal_surname",
            "maternal_surname",
            "email",
            "person_role",
            "created_at",
            "updated_at",
        ]


class CurrentUserSerializer(serializers.ModelSerializer):
    person = CurrentPersonSerializer(read_only=True)
    user_role = UserRoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "person",
            "user_role",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "created_at",
            "updated_at",
        ]


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()
    user = CurrentUserSerializer()


def validate_password_confirmation(attrs):
    if attrs["new_password"] != attrs["new_password_confirm"]:
        raise serializers.ValidationError(
            {
                "new_password_confirm": serializers.ErrorDetail(
                    "Las contraseñas no coinciden.",
                    code="password_mismatch",
                )
            }
        )
    return attrs


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("current_password"),
    )
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("new_password"),
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("new_password_confirm"),
    )

    def validate(self, attrs):
        return validate_password_confirmation(attrs)


class PasswordForgotSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            **field_errors("email"),
            "invalid": "El campo email debe contener un correo electrónico válido.",
        }
    )

    def validate_email(self, value):
        return value.strip().casefold()


class PasswordConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        error_messages=field_errors("token"),
    )
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("new_password"),
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("new_password_confirm"),
    )

    def validate(self, attrs):
        return validate_password_confirmation(attrs)

    def validate_token(self, value):
        candidate = value.strip()

        if "://" in candidate:
            token_values = parse_qs(urlparse(candidate).query).get("token")
            if not token_values:
                raise serializers.ValidationError(
                    "El enlace no contiene un token válido.",
                    code="invalid_token_format",
                )
            candidate = token_values[0]
        elif candidate.startswith("token="):
            token_values = parse_qs(candidate).get("token")
            if not token_values:
                raise serializers.ValidationError(
                    "El valor no contiene un token válido.",
                    code="invalid_token_format",
                )
            candidate = token_values[0]
        else:
            candidate = unquote(candidate)

        if not candidate:
            raise serializers.ValidationError(
                "El token no puede estar vacío.",
                code="blank",
            )
        return candidate


class MessageResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
