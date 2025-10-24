#serializers.py
from rest_framework import serializers
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, RolUser, Persona

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

class PersonaSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Persona
        fields = ['nombres', 'apellido_paterno', 'email']

class UserListSerializer(serializers.ModelSerializer):
    rol_user = RolUserSerializer(read_only=True)
    persona = PersonaSummarySerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'rol_user', 'persona']
