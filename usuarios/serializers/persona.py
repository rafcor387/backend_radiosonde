from rest_framework import serializers
from usuarios.models import Persona, RolPersona
from .rol import RolPersonaSerializer

class PersonaSerializer(serializers.ModelSerializer):
    rol_persona = RolPersonaSerializer(read_only=True)

    class Meta:
        model = Persona
        fields = ['id', 'nombres', 'apellido_paterno','apellido_materno','rol_persona', 'email'] #esto se ve en el get
        read_only_fields = ['id']
        # este no se vera ni se editara en el json body del post, en el post se vera  lo de fields pero no lo de read_only_fields
    
    def validate_nombres(self, value):
        if not value[0].isupper():
            raise serializers.ValidationError("El nombre debe empezar con mayúscula")
        return value
    
    def validate(self, data):
        if data['nombres'] == data['apellido_paterno']:
            raise serializers.ValidationError("Nombre y apellido no pueden ser iguales")
        return data
    
    """ def validate_nombres(self, value):
        if value != 'Juan':
            raise serializers.ValidationError("El nombre debe ser Juan")
        return value """
    
    
    def create(self, validated_data):
        nombre = validated_data.get('nombres', '')

        if nombre != 'Juan':
            raise serializers.ValidationError({"nombres": "El nombre debe ser Juan"})

        return super().create(validated_data)

    # 2. ESTO PASA EN EL PUT / PATCH (EDITAR)
    def update(self, instance, validated_data):
        # Aquí NO ponemos ninguna regla de mayúsculas.
        # Simplemente dejamos que Django haga el SQL UPDATE.
        return super().update(instance, validated_data)
    
    