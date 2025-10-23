from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated
from .services import enviar_correo 
from .serializers import LoginSerializer
from .permissions import IsAdminUser

from rest_framework.generics import ListAPIView # ¡Importa la vista genérica!
from .models import User # Importa el modelo User
from .serializers import UserListSerializer # ¡Importa tu nuevo serializer!


class LoginView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            tokens = serializer.save()
            return Response(tokens, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class MeView(APIView): 
    permission_classes = [IsAuthenticated]  

    def get(self, request):
        user = request.user
        return Response({"username": user.username}, status=status.HTTP_200_OK)
    
class EmailsendView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]  

    def post(self, request): 
        receiver_email = request.data.get('RECEIVER_EMAIL')

        if not receiver_email:
            return Response({'error': 'El campo RECEIVER_EMAIL es obligatorio.'}, status=status.HTTP_400_BAD_REQUEST)

        exito = enviar_correo(receiver_email)

        if exito:
            return Response({'message': f'Correo enviado exitosamente a {receiver_email}.'}, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'No se pudo enviar el correo.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        
class UserListView(ListAPIView):
    """
    Vista para listar todos los usuarios del sistema.
    - Solo accesible para administradores.
    - Utiliza el UserListSerializer para formatear la salida.
    """
    # 1. ¿Qué objetos vamos a listar? Todos los usuarios.
    queryset = User.objects.all().order_by('id')
    
    # 2. ¿Cómo los vamos a convertir a JSON? Con este serializer.
    serializer_class = UserListSerializer
    
    # 3. ¿Quién puede acceder? Solo administradores autenticados.
    permission_classes = [IsAuthenticated, IsAdminUser]