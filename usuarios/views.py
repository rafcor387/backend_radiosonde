from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated
from .services import enviar_correo 
from .serializers import LoginSerializer
from .permissions import IsAdminUser
from django.conf import settings
from rest_framework.generics import ListAPIView 
from .models import User, Persona, Invitacion
from .serializers import UserListSerializer 


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
    def post(self, request):
        receiver_email = request.data.get('RECEIVER_EMAIL')
        if not receiver_email:
            return Response(...)

        if Persona.objects.filter(email=receiver_email).exists():
            return Response({'error': 'Ya existe una persona o invitación para este email.'}, status=status.HTTP_400_BAD_REQUEST)

        persona_invitada = Persona.objects.create(email=receiver_email)

        invitacion = Invitacion.objects.create(
            guest=persona_invitada,
            host=request.user
        )

        frontend_url = 'http://localhost:3000/register'
        invitacion_url = f"{frontend_url}?token={invitacion.token}"

        asunto = "Has sido invitado a nuestro sistema"
        mensaje = (
            f"¡Hola!\n\n"
            f"Has sido invitado a unirte a nuestro sistema por {request.user.username}.\n"
            f"Para completar tu registro, por favor haz clic en el siguiente enlace:\n\n"
            f"{invitacion_url}\n\n"
            f"¡Te esperamos!"
        )
        
        from django.core.mail import send_mail
        send_mail(asunto, mensaje, settings.DEFAULT_FROM_EMAIL, [receiver_email])
        
        return Response({'message': f'Invitación enviada exitosamente a {receiver_email}.'}, status=status.HTTP_201_CREATED)
            
        
class UserListView(ListAPIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    queryset = User.objects.all().order_by('id')
    
    serializer_class = UserListSerializer
    