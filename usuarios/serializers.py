#serializers.py
from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, RolUser, Persona,RolPersona,Invitacion

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()         
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")

        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError("Credenciales inválidas")

        attrs["user"] = user
        return attrs

    def create(self, validated_data):
        user = validated_data["user"]
        refresh = RefreshToken.for_user(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }

class RolUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolUser
        fields = ['nombre']

class RolPersonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolPersona
        fields = ['nombre']

class PersonaSerializer(serializers.ModelSerializer):
    rol_persona = RolPersonaSerializer(read_only=True)
    rol_persona_id = serializers.PrimaryKeyRelatedField(
        queryset=RolPersona.objects.all(),
        source='rol_persona', 
        write_only=True,
        required=True,
        allow_null=False
    )
    class Meta:
        model = Persona
        fields = ['id','nombres', 'apellido_paterno', 'apellido_materno', 'email', 'rol_persona', 'rol_persona_id','created']
        read_only_fields = ['id', 'created']
    
    def validate_email(self, value):
        """Validar email único"""
        # Si es creación
        if not self.instance:
            if Persona.objects.filter(email=value).exists():
                raise serializers.ValidationError(f"El email {value} ya está registrado.")
        # Si es actualización
        else:
            if Persona.objects.filter(email=value).exclude(id=self.instance.id).exists():
                raise serializers.ValidationError(f"El email {value} ya está registrado.")
        return value

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
        read_only_fields = ['id','username']
    
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
    
class NuevoUsuarioPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=6, write_only=True)
    
    # Opcional: Si quieres confirmación de contraseña
    # password_confirm = serializers.CharField(min_length=6, write_only=True) 