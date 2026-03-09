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

class LoginView(APIView):
    permission_classes = []
    serializer_class = LoginSerializer  # Swagger ahora verá los campos

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
    # Aquí podríamos crear un serializer simple para que Swagger muestre RECEIVER_EMAIL
    def post(self, request):
        receiver_email = request.data.get('RECEIVER_EMAIL')
        if not receiver_email:
            return Response({'error': 'Email obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

        if Persona.objects.filter(email=receiver_email).exists():
            return Response({'error': 'Ya existe una invitación para este email.'},
status=status.HTTP_400_BAD_REQUEST)

        persona_invitada = Persona.objects.create(email=receiver_email)
        invitacion = Invitacion.objects.create(guest=persona_invitada, host=request.user)

        url = f"http://localhost:3000/register?token={invitacion.token}&id={persona_invitada.id}"
        send_mail("Invitación al sistema", f"Enlace: {url}", settings.DEFAULT_FROM_EMAIL, [receiver_email])

        return Response({'message': 'Invitación enviada.'}, status=status.HTTP_201_CREATED)