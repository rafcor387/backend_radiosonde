from rest_framework import serializers
from usuarios.models import RolUser, RolPersona

class RolUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolUser
        fields = ['nombre']

class RolPersonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolPersona
        fields = ['nombre']