from rest_framework.permissions import BasePermission

class IsAdminUser(BasePermission):
    """
    Permiso personalizado para permitir el acceso solo a usuarios con rol de Administrador.
    Asume que el ID del rol de Administrador es 1.
    """
    message = "Solo los administradores pueden realizar esta acción."

    def has_permission(self, request, view):
        # Ahora, verificamos la lógica del rol.
        # 1. ¿El usuario tiene un rol asignado?
        # 2. ¿El ID de ese rol es 1?
        return request.user.rol_user is not None and request.user.rol_user.id == 1