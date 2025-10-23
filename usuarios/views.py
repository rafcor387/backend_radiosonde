from .services import enviar_correo_de_prueba 
from .serializers import LoginSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated
# Nuevas importaciones de DRF
# Las otras importaciones siguen igual

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
    

@api_view(['POST']) # Un solo decorador hace todo el trabajo
def enviar_correo_api_view(request): # Le cambiamos el nombre para no confundir
    # request.data ya tiene el JSON parseado, sin importar el formato de entrada
    receiver_email = request.data.get('RECEIVER_EMAIL')

    if not receiver_email:
        # Usamos Response de DRF y las constantes de status
        return Response({'error': 'El campo RECEIVER_EMAIL es obligatorio.'}, status=status.HTTP_400_BAD_REQUEST)

    exito = enviar_correo_de_prueba(receiver_email)

    if exito:
        return Response({'message': f'Correo enviado exitosamente a {receiver_email}.'}, status=status.HTTP_200_OK)
    else:
        return Response({'error': 'No se pudo enviar el correo.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)