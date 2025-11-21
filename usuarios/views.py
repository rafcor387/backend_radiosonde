#usuarios/views.py
from rest_framework.views import APIView
from django.db import transaction
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from .permissions import HasValidInvitationToken
from django.conf import settings
from rest_framework.generics import ListAPIView 
from .models import User, Persona, Invitacion,RolUser
from .serializers import (
    LoginSerializer,
    PersonaSerializer,
    UserSerializer,
    NuevoUsuarioPasswordSerializer
)
from django.shortcuts import get_object_or_404


class CompletarRegistroUserView(APIView):
    """
    Paso final: Recibe password y Token.
    Crea el usuario linkeado a la persona y quema el token.
    """
    # SOLO permite entrar si trae el header 'Invitation-Token' válido
    permission_classes = [HasValidInvitationToken] 

    def post(self, request):
        serializer = NuevoUsuarioPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # 1. Obtener el token del header (Ya sabemos que es válido por el permiso)
        token = request.META.get('HTTP_INVITATION_TOKEN')
        
        try:
            # Recuperamos la invitación
            invitacion = Invitacion.objects.get(token=token, estado='ENTREGADA')
            persona = invitacion.guest
            
            # Validaciones extra de seguridad
            if User.objects.filter(username=persona.email).exists():
                return Response(
                    {'error': 'Ya existe un usuario registrado con este email.'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Invitacion.DoesNotExist:
            # Esto raramente pasará si el permiso HasValidInvitationToken funciona bien
            return Response({'error': 'Token inválido'}, status=status.HTTP_403_FORBIDDEN)

        # 2. Iniciar transacción atómica (Todo o nada)
        with transaction.atomic():
            password = serializer.validated_data['password']
            
            # Buscar Rol User ID 2 (Usuario Normal)
            try:
                rol_normal = RolUser.objects.get(id=2)
            except RolUser.DoesNotExist:
                # Fallback por si no existe el rol 2 en tu DB
                rol_normal = None 

            # 3. CREAR EL USUARIO
            user = User.objects.create_user(
                username=persona.email, # El email viene de la Persona (Seguro)
                password=password,
                persona=persona,
                rol_user=rol_normal,
                is_staff=True, # <--- Lo que pediste
                # is_active=True y created se ponen solos por el modelo
            )

            # 4. ACTUALIZAR LA INVITACIÓN
            invitacion.estado = 'ACEPTADA'
            invitacion.host = user # Opcional: Guardamos quién aceptó (auto-referencia) o lo dejamos null
            invitacion.save()

        return Response(
            {'message': 'Cuenta creada exitosamente. Ahora puedes iniciar sesión.'}, 
            status=status.HTTP_201_CREATED
        )
    


    
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
            # Es buena práctica devolver un error claro si falta el campo
            return Response({'error': 'El campo RECEIVER_EMAIL es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)

        if Persona.objects.filter(email=receiver_email).exists():
            return Response({'error': 'Ya existe una persona o invitación para este email.'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Creamos la Persona (Aquí se genera el ID automáticamente)
        persona_invitada = Persona.objects.create(email=receiver_email)

        # 2. Creamos la Invitación (Aquí se genera el Token automáticamente)
        invitacion = Invitacion.objects.create(
            guest=persona_invitada,
            host=request.user
        )

        frontend_url = 'http://localhost:3000/register'
        
        # --- CAMBIO AQUÍ ---
        # Agregamos el parámetro "&id=" con el ID de la persona creada
        invitacion_url = f"{frontend_url}?token={invitacion.token}&id={persona_invitada.id}"
        # -------------------

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
    
class UserDetailView(APIView):
    """
    Vista para TODAS las operaciones de usuario:
    - Listar todos (GET sin id)
    - Obtener uno (GET con id)
    - Actualizar (PUT/PATCH con id)
    - Eliminar (DELETE con id)
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Crear un nuevo usuario (opcional - si lo necesitas)
        Solo administradores
        """
        if not request.user.is_staff:
            return Response(
                {'error': 'Solo administradores pueden crear usuarios'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def get(self, request, user_id=None):
        """
        Obtener un usuario específico o listar todos
        """
        # Si NO hay user_id, listar todos los usuarios
        if user_id is None:
            # Solo admin puede ver todos los usuarios
            if not request.user.is_staff:
                return Response(
                    {'error': 'Solo administradores pueden listar usuarios'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            users = User.objects.all().order_by('id')
            serializer = UserSerializer(users, many=True)
            return Response(serializer.data)
        
        # Si HAY user_id, obtener usuario específico
        user = get_object_or_404(User, id=user_id)
        
        # Solo admin o el mismo usuario pueden ver detalles
        if not request.user.is_staff and request.user.id != user.id:
            return Response(
                {'error': 'No tienes permisos para ver este usuario'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UserSerializer(user)
        return Response(serializer.data)
    
    def put(self, request, user_id):
        """Actualización completa de un usuario"""
        user = get_object_or_404(User, id=user_id)
        
        # Solo admin puede editar cualquier usuario
        if not request.user.is_staff:
            return Response(
                {'error': 'Solo administradores pueden editar usuarios'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = UserSerializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request, user_id):
        """Actualización parcial de un usuario y su persona"""
        user = get_object_or_404(User, id=user_id)
        
        # Verificar permisos
        if not request.user.is_staff:
            # Usuario normal solo puede editar su propia info
            if request.user.id != user.id:
                return Response(
                    {'error': 'No tienes permisos para editar este usuario'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Usuario normal no puede cambiar roles
            if 'rol_user_id' in request.data:
                return Response(
                    {'error': 'No puedes cambiar tu propio rol de usuario'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Verificar si intenta cambiar rol de persona
            persona_data = request.data.get('persona', {})
            if 'rol_persona_id' in persona_data:
                return Response(
                    {'error': 'No puedes cambiar tu propio rol de persona'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, user_id):
        """Eliminar un usuario - Solo admin"""
        # Solo admin puede eliminar
        if not request.user.is_staff:
            return Response(
                {'error': 'Solo administradores pueden eliminar usuarios'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user = get_object_or_404(User, id=user_id)
        
        # No permitir auto-eliminación
        if request.user.id == user.id:
            return Response(
                {'error': 'No puedes eliminar tu propia cuenta'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Guardar info antes de eliminar
        username = user.username
        
        # Si tiene persona asociada, también se eliminará (por CASCADE)
        user.delete()
        
        return Response(
            {'message': f'Usuario {username} eliminado correctamente'},
            status=status.HTTP_200_OK
        )

class PersonaView(APIView):
    def get_permissions(self):
        if self.request.method == 'PATCH':
            return [HasValidInvitationToken()]
        
        return [IsAuthenticated(), IsAdminUser()]
    
    def patch(self, request, persona_id):
        persona = get_object_or_404(Persona, id=persona_id)

        token_header = request.META.get('HTTP_INVITATION_TOKEN')
        invitacion = Invitacion.objects.filter(token=token_header).first()

        if invitacion.guest.id != persona.id:
             return Response(
                 {'error': 'Este token no pertenece a la persona que intentas editar.'}, 
                 status=status.HTTP_403_FORBIDDEN
             )
        
        serializer = PersonaSerializer(persona, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def get(self, request, persona_id=None):
        if persona_id is None:
            if not request.user.is_staff:
                # Usuario normal solo ve su propia persona
                if hasattr(request.user, 'persona'):
                    serializer = PersonaSerializer(request.user.persona)
                    return Response(serializer.data)
                return Response(
                    {'error': 'No tienes una persona asociada'},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            personas = Persona.objects.all().order_by('-created')
            serializer = PersonaSerializer(personas, many=True)
            return Response({
                'count': personas.count(),
                'personas': serializer.data
            })
        persona = get_object_or_404(Persona, id=persona_id)
        
        if not request.user.is_staff:
            if not hasattr(request.user, 'persona') or request.user.persona.id != persona.id:
                return Response(
                    {'error': 'No tienes permisos para ver esta persona'},
                    status=status.HTTP_403_FORBIDDEN
                )
        serializer = PersonaSerializer(persona)
        return Response(serializer.data)
    
    def post(self, request):
        """Crear nueva persona - Solo admin"""
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Solo administradores pueden crear personas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = PersonaSerializer(data=request.data)
        
        if serializer.is_valid():
            persona = serializer.save()
            return Response(
                serializer.data,  # El mismo serializer devuelve los datos
                status=status.HTTP_201_CREATED
            )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def put(self, request, persona_id):
        """Actualización completa"""
        persona = get_object_or_404(Persona, id=persona_id)
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Solo administradores pueden editar personas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = PersonaSerializer(persona, data=request.data)
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, persona_id):
        """Eliminar persona - Solo admin"""
        
        if not request.user.is_staff:
            return Response(
                {'error': 'Solo administradores pueden eliminar personas'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        persona = get_object_or_404(Persona, id=persona_id)
        
        # Validaciones antes de eliminar
        if hasattr(persona, 'user'):
            return Response(
                {'error': 'No se puede eliminar una persona que tiene usuario asociado'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if hasattr(persona, 'invitacion'):
            return Response(
                {'error': 'No se puede eliminar una persona con invitación pendiente'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        email = persona.email
        persona.delete()
        
        return Response(
            {'message': f'Persona {email} eliminada correctamente'},
            status=status.HTTP_200_OK
        )