from rest_framework.permissions import BasePermission
from rest_framework import permissions
from .models import Invitacion

class IsAdminUser(BasePermission):
    message = "Solo los administradores pueden realizar esta acción."

    def has_permission(self, request, view):
        # Convertimos el nombre a minúsculas para evitar problemas con mayúsculas/minúsculas
        return bool(
            request.user and 
            request.user.is_authenticated and 
            request.user.rol_user and 
            request.user.rol_user.nombre.lower() == 'administrador'
        )
    
class HasValidInvitationToken(permissions.BasePermission):
    """
    Permite el acceso si en los HEADERS viene un token de invitación válido.
    Header esperado: 'Invitation-Token'
    """
    def has_permission(self, request, view):
        token = request.META.get('HTTP_INVITATION_TOKEN')
        
        if not token:
            return False 

        try:
            Invitacion.objects.get(token=token, estado='ENTREGADA')
            return True 
        except Invitacion.DoesNotExist:
            return False 