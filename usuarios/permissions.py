from rest_framework.permissions import BasePermission

from usuarios.models import UserRole


class IsAdministrator(BasePermission):
    message = "Solo un administrador puede realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.deleted_at is None
            and user.user_role.code == UserRole.Code.ADMINISTRATOR
        )
