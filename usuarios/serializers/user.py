from rest_framework import serializers

from usuarios.models import PersonRole, User


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
