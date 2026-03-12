from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from usuarios.models import Persona
from usuarios.serializers import PersonaSerializer
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.shortcuts import get_object_or_404

class PersonaSimpleView(APIView):
    serializer_class = PersonaSerializer
    permission_classes = [AllowAny]

    def get(self, request):
        personas = Persona.objects.filter(DeleteDate__isnull=True)
        serializer = self.serializer_class(personas, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors)
    
class PersonaDetailView(APIView):
    serializer_class = PersonaSerializer
    permission_classes = [AllowAny]
    
    def get(self,request,pk):
        persona = Persona.objects.get(id=pk)
        serializer = self.serializer_class(persona)
        return Response(serializer.data)
    
    def patch(self, request, pk): 
        persona = Persona.objects.get(id=pk) 
        serializer = PersonaSerializer(persona, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save() 
            return Response(serializer.data)
        return Response(serializer.errors)
    
    def delete(self, request, pk):
        #persona = Persona.objects.get(id=pk)
        persona = get_object_or_404(Persona, id=pk)

        persona.DeleteDate = timezone.now() 
        persona.save()

        return Response({"message": "Eliminado lógicamente"})