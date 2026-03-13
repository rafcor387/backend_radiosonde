from rest_framework import serializers
from usuarios.models import Persona, RolPersona
from .rol import RolPersonaSerializer

class PersonaSerializer(serializers.ModelSerializer):
    rol_persona_detail = RolPersonaSerializer(source='rol_persona', read_only=True)

    class Meta:
        model = Persona
        fields = ['id', 'nombres', 'apellido_paterno','apellido_materno','email','rol_persona','rol_persona_detail'] #esto se ve en el get
        read_only_fields = ['id']
        # este no se vera ni se editara en el json body del post, en el post se vera  lo de fields pero no lo de read_only_fields
    
    def validate_nombres(self, value):
        if not value[0].isupper():
            raise serializers.ValidationError("El nombre debe empezar con mayúscula")
        return value
    
    
    def validate(self, data):
        # 1. Intentamos obtener los dos valores
        nombres = data.get('nombres')
        apellido = data.get('apellido_paterno')
        # 2. SOLO si el usuario está intentando cambiar AMBOS a la vez, los comparamos
        if nombres is not None and apellido is not None:
            if nombres != 'apellido':
                raise serializers.ValidationError("No pueden ser iguales")
        # 3. Si solo envió uno de los dos, o ninguno, saltamos la validación
        return data
    
    