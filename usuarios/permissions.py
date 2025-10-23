from rest_framework.permissions import BasePermission

class IsAdminUser(BasePermission):
    message = "Solo los administradores pueden realizar esta acción."

    def has_permission(self, request, view):
        return request.user.rol_user is not None and request.user.rol_user.id == 1