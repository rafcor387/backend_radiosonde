from rest_framework import serializers

from usuarios.models import Person, PersonRole, User, UserRole
from usuarios.serializers.authentication import (
    PersonRoleSerializer,
    UserRoleSerializer,
    field_errors,
)


class UserListPersonSerializer(serializers.ModelSerializer):
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
        ]


class UserListSerializer(serializers.ModelSerializer):
    person = UserListPersonSerializer(read_only=True)
    user_role = UserRoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "person",
            "user_role",
            "is_active",
        ]


class UserListQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(
        required=False,
        default=1,
        min_value=1,
        error_messages={
            "invalid": "El campo page debe ser un número entero.",
            "min_value": "El campo page debe ser mayor o igual a 1.",
        },
    )
    username = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=20,
        error_messages=field_errors("username"),
    )
    person_role = serializers.ChoiceField(
        required=False,
        choices=PersonRole.Code.choices,
        error_messages={
            **field_errors("person_role"),
            "invalid_choice": "El rol de persona seleccionado no es válido.",
        },
    )
    user_role = serializers.ChoiceField(
        required=False,
        choices=UserRole.Code.choices,
        error_messages={
            **field_errors("user_role"),
            "invalid_choice": "El rol de usuario seleccionado no es válido.",
        },
    )
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=302,
        error_messages=field_errors("name"),
    )
    is_active = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        error_messages={
            **field_errors("is_active"),
            "invalid": "El campo is_active debe ser verdadero o falso.",
        },
    )


class UserPaginatedListSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    items = UserListSerializer(many=True)


class UserDetailPersonSerializer(UserListPersonSerializer):
    class Meta(UserListPersonSerializer.Meta):
        fields = [
            *UserListPersonSerializer.Meta.fields,
            "created_at",
        ]


class UserDetailSerializer(serializers.ModelSerializer):
    person = UserDetailPersonSerializer(read_only=True)
    user_role = UserRoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "person",
            "user_role",
            "is_active",
            "created_at",
        ]


class UserUpdateSerializer(serializers.Serializer):
    person_role_code = serializers.ChoiceField(
        choices=PersonRole.Code.choices,
        required=False,
        error_messages={
            **field_errors("person_role_code"),
            "invalid_choice": "El rol de persona seleccionado no es válido.",
        },
    )
    user_role_code = serializers.ChoiceField(
        choices=UserRole.Code.choices,
        required=False,
        error_messages={
            **field_errors("user_role_code"),
            "invalid_choice": "El rol de usuario seleccionado no es válido.",
        },
    )
    is_active = serializers.BooleanField(
        required=False,
        error_messages={
            **field_errors("is_active"),
            "invalid": "El campo is_active debe ser verdadero o falso.",
        },
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Debe enviar al menos un campo permitido para actualizar."
            )
        return attrs


class OwnProfileUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=False,
        error_messages=field_errors("name"),
    )
    paternal_surname = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=False,
        error_messages=field_errors("paternal_surname"),
    )
    maternal_surname = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=False,
        error_messages=field_errors("maternal_surname"),
    )

    def validate(self, attrs):
        unknown_fields = set(self.initial_data) - set(self.fields)
        if unknown_fields:
            raise serializers.ValidationError(
                {
                    field: serializers.ErrorDetail(
                        "Este campo no está permitido.",
                        code="not_allowed",
                    )
                    for field in sorted(unknown_fields)
                }
            )
        if not attrs:
            raise serializers.ValidationError(
                "Debe enviar al menos un campo permitido para actualizar."
            )
        return attrs


class BootstrapAdminSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, allow_blank=False)
    paternal_surname = serializers.CharField(max_length=100, allow_blank=False)
    maternal_surname = serializers.CharField(max_length=100, allow_blank=False)
    email = serializers.EmailField()
    person_role_code = serializers.ChoiceField(choices=PersonRole.Code.choices)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError(
                {"password_confirm": "Las contraseñas no coinciden."}
            )
        return attrs


class BootstrapAdminResponseSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="person.email", read_only=True)
    name = serializers.CharField(source="person.name", read_only=True)
    paternal_surname = serializers.CharField(
        source="person.paternal_surname",
        read_only=True,
    )
    maternal_surname = serializers.CharField(
        source="person.maternal_surname",
        read_only=True,
    )
    person_role = serializers.CharField(
        source="person.person_role.code",
        read_only=True,
    )
    user_role = serializers.CharField(source="user_role.code", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "name",
            "paternal_surname",
            "maternal_surname",
            "person_role",
            "user_role",
            "is_active",
            "is_staff",
            "is_superuser",
        ]
