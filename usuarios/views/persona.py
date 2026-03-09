from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from usuarios.models import Persona
from usuarios.serializers import PersonaSerializer

class PersonaView(APIView):
    serializer_class = PersonaSerializer
    @extend_schema(responses={200: PersonaSerializer(many=True)})
    
    def get(self, request, persona_id=None):
        if persona_id is None:
            personas = Persona.objects.all()
            serializer = self.serializer_class(personas, many=True)
            return Response(serializer.data)
        persona = get_object_or_404(Persona, id=persona_id)
        serializer = self.serializer_class(persona)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)