from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.conf import settings
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema
from usuarios.models import User, Persona, Invitacion, RolUser
from usuarios.serializers import LoginSerializer, NuevoUsuarioPasswordSerializer
from ..permissions import HasValidInvitationToken
from usuarios.serializers.auth import InvitacionEmailSerializer 
from rest_framework.permissions import AllowAny

class LoginView(APIView):
    permission_classes = []
    serializer_class = LoginSerializer 

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            tokens = serializer.save()
            return Response(tokens, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CompletarRegistroUserView(APIView):
    permission_classes = [HasValidInvitationToken]
    serializer_class = NuevoUsuarioPasswordSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        token = request.META.get('HTTP_INVITATION_TOKEN')
        try:
            invitacion = Invitacion.objects.get(token=token, estado='ENTREGADA')
            persona = invitacion.guest
            if User.objects.filter(username=persona.email).exists():
                return Response({'error': 'Email ya registrado.'}, status=status.HTTP_400_BAD_REQUEST)

            with transaction.atomic():
                rol_normal = RolUser.objects.filter(id=2).first()
                user = User.objects.create_user(
                    username=persona.email,
                    password=serializer.validated_data['password'],
                    persona=persona,
                    rol_user=rol_normal,
                    is_staff=True
                )
                invitacion.estado = 'ACEPTADA'
                invitacion.save()
            return Response({'message': 'Cuenta creada.'}, status=status.HTTP_201_CREATED)
        except Invitacion.DoesNotExist:
            return Response({'error': 'Token inválido'}, status=status.HTTP_403_FORBIDDEN)

class EmailsendView(APIView):
    permission_classes = [AllowAny]
    serializer_class = InvitacionEmailSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        receiver_email = serializer.validated_data.get('RECEIVER_EMAIL')
        
        if not receiver_email:
            return Response({'error': 'Email obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

        if Persona.objects.filter(email=receiver_email).exists():
            return Response({'error': 'Ya existe una invitación para este email.'},status=status.HTTP_400_BAD_REQUEST)

        invitacion = Invitacion.objects.create(
            email=receiver_email, 
            usuario=request.user
            )
        
        frontend_url = 'http://localhost:3000/register'

        asunto = "Has sido invitado a nuestro sistema"
        mensaje = (
            f"¡Hola!\n\n"
            f"Has sido invitado a unirte a nuestro sistema por {request.user.username}.\n"
            f"Para completar tu registro, entra a nuestra pagina: {frontend_url}\n\n"
            f"Debes usar tu token {invitacion.token} para poder Crear una Cuenta.\n\n"
            f"¡Te esperamos!"
        )
        
        send_mail(asunto, mensaje, settings.DEFAULT_FROM_EMAIL, [receiver_email])
        
        new_guest = Persona.objects.create(email=receiver_email, rol_persona_id=2)
        invitacion.persona = new_guest
        invitacion.save()
                
        return Response({'message': f'Invitación enviada exitosamente a {receiver_email}.'}, status=status.HTTP_201_CREATED)