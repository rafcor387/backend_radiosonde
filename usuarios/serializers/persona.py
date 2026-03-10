from rest_framework import serializers
from usuarios.models import Persona, RolPersona
from .rol import RolPersonaSerializer

class PersonaSerializer(serializers.ModelSerializer):
    # 1. EL "DTO" (Definición de campos)
    class Meta:
        model = Persona
        fields = ['id', 'nombres', 'apellido_paterno', 'apellido_materno', 'email', 'rol_persona','rol_persona_id']
        read_only_fields = ['id']
        
    rol_persona = RolPersonaSerializer(read_only=True)
    rol_persona_id = serializers.PrimaryKeyRelatedField(
        queryset=RolPersona.objects.all(),
        source='rol_persona',
        write_only=True,
        required=True,
        allow_null=False
    )



    def validate_email(self, value):
        if not self.instance:
            if Persona.objects.filter(email=value).exists():
                raise serializers.ValidationError(f"El email {value} ya está registrado.")
        else:
            if Persona.objects.filter(email=value).exclude(id=self.instance.id).exists():
                raise serializers.ValidationError(f"El email {value} ya está registrado.")
        return value