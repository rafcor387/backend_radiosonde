from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from usuarios.models import Persona
from usuarios.serializers import PersonaSerializer

class PersonaListCreateView(APIView):
    serializer_class = PersonaSerializer

    @extend_schema(summary="Listar todas las personas")
    def get(self, request):
        personas = Persona.objects.all()
        # "many=True" le dice a Django que es una lista de objetos
        serializer = self.serializer_class(personas, many=True)
        return Response(serializer.data)

    @extend_schema(summary="Crear una nueva persona")
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class PersonaDetailView(APIView):
    serializer_class = PersonaSerializer

    @extend_schema(summary="Ver detalle de una persona")
    def get(self, request, pk):
        persona = Persona.objects.get(pk=pk) # Busca por ID
        serializer = self.serializer_class(persona)
        return Response(serializer.data)

    @extend_schema(summary="Actualizar una persona")
    def put(self, request, pk):
        persona = Persona.objects.get(pk=pk)
        # Pasamos el objeto actual + la nueva data
        serializer = self.serializer_class(persona, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary="Borrar una persona")
    def delete(self, request, pk):
        persona = Persona.objects.get(pk=pk)
        persona.delete() # Borra de la base de datos
        return Response(status=status.HTTP_204_NO_CONTENT)