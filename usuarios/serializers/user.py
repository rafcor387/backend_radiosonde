from rest_framework import serializers
from usuarios.models import User, RolUser
from .rol import RolUserSerializer
from .persona import PersonaSerializer

class UserSerializer(serializers.ModelSerializer):
    rol_user = RolUserSerializer(read_only=True)
    rol_user_id = serializers.PrimaryKeyRelatedField(
        queryset=RolUser.objects.all(),
        source='rol_user',
        write_only=True,
        required=False,
        allow_null=True
    )
    persona = PersonaSerializer()

    class Meta:
        model = User
        fields = ['id', 'username', 'rol_user', 'rol_user_id', 'persona']
        read_only_fields = ['id', 'username']

    def update(self, instance, validated_data):
        persona_data = validated_data.pop('persona', None)
        instance = super().update(instance, validated_data)

        if persona_data and instance.persona:
            persona_instance = instance.persona
            for attr, value in persona_data.items():
                setattr(persona_instance, attr, value)
            persona_instance.save()

        instance.refresh_from_db()
        return instance