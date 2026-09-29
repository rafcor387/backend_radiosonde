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
