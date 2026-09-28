from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

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
        
        # 1. Tomamos el Access Token generado
        access_token = refresh.access_token
        
        # 2. Inyectamos información extra DENTRO del token (Claims)
        access_token['email'] = user.username
        access_token['rol'] = user.rol_user.nombre

        # Si quisieras meter el nombre de la persona también:
        if hasattr(user, 'persona') and user.persona:
            access_token['nombre_completo'] = f"{user.persona.nombres} {user.persona.apellido_paterno}"

        # 3. Retornamos SOLO el access token (ya no devolvemos el refresh)
        return {
            "access": str(access_token),
            "rolName" : user.rol_user.nombre
        }

class NuevoUsuarioPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=6, write_only=True)
    
class InvitacionEmailSerializer(serializers.Serializer):
    RECEIVER_EMAIL = serializers.EmailField(
        required=True,
        help_text="El correo electrónico de la persona a la que quieres invitar."
    )