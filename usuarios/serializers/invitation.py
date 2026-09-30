from rest_framework import serializers

from usuarios.models import Invitation, PersonRole
from usuarios.serializers.authentication import (
    PersonRoleSerializer,
    field_errors,
)


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={
            **field_errors("email"),
            "invalid": "El campo email debe contener un correo electrónico válido.",
        }
    )
    person_role_code = serializers.ChoiceField(
        choices=PersonRole.Code.choices,
        error_messages={
            **field_errors("person_role_code"),
            "invalid_choice": "El rol de persona seleccionado no es válido.",
        },
    )

    def validate_email(self, value):
        return value.strip().casefold()


class InvitationResponseSerializer(serializers.ModelSerializer):
    person_role = PersonRoleSerializer(read_only=True)

    class Meta:
        model = Invitation
        fields = [
            "id",
            "email",
            "person_role",
            "status",
            "expires_at",
            "created_at",
            "updated_at",
        ]


class InvitationValidationDetailsSerializer(serializers.ModelSerializer):
    person_role = PersonRoleSerializer(read_only=True)

    class Meta:
        model = Invitation
        fields = ["email", "person_role", "status", "expires_at"]


class InvitationValidationResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    invitation = InvitationValidationDetailsSerializer()


class InvitationAcceptSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=100,
        error_messages=field_errors("name"),
    )
    paternal_surname = serializers.CharField(
        max_length=100,
        error_messages=field_errors("paternal_surname"),
    )
    maternal_surname = serializers.CharField(
        max_length=100,
        error_messages=field_errors("maternal_surname"),
    )
    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("password"),
    )
    password_confirm = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        error_messages=field_errors("password_confirm"),
    )

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {
                    "password_confirm": serializers.ErrorDetail(
                        "Las contraseñas no coinciden.",
                        code="password_mismatch",
                    )
                }
            )
        return attrs
