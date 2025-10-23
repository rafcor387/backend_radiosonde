#serializers.py
from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, RolUser

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
    """Serializer para mostrar el nombre del rol."""
    class Meta:
        model = RolUser
        fields = ['nombre']

class UserListSerializer(serializers.ModelSerializer):
    """
    Serializer para listar usuarios. Define qué campos se mostrarán en la API.
    """
    # Usamos el RolUserSerializer para mostrar el nombre del rol en lugar de solo su ID.
    # 'read_only=True' porque no queremos que se pueda modificar el rol desde este endpoint.
    rol_user = RolUserSerializer(read_only=True)

    class Meta:
        model = User
        # Lista de los campos que quieres que aparezcan en el JSON
        fields = ['id', 'username', 'rol_user', 'date_joined']
        # ¡NUNCA incluyas 'password' en un serializer de lectura!