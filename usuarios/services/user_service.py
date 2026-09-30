from django.conf import settings
from django.db import transaction

from usuarios.error_codes import ErrorCode
from usuarios.exceptions import ServiceError
from usuarios.models import Person, PersonRole, User, UserRole
from usuarios.services.username_service import (
    UsernameGenerationError,
    UsernameService,
)


class UserServiceError(ServiceError):
    pass


class UserService:
    @staticmethod
    def list_all():
        return (
            User.objects.filter(
                deleted_at__isnull=True,
                person__deleted_at__isnull=True,
            )
            .select_related("person__person_role", "user_role")
            .order_by("id")
        )

    @staticmethod
    def get_by_id(*, user_id):
        user = (
            User.objects.filter(
                pk=user_id,
                deleted_at__isnull=True,
                person__deleted_at__isnull=True,
            )
            .select_related("person__person_role", "user_role")
            .first()
        )
        if user is None:
            raise UserServiceError(
                ErrorCode.USER_NOT_FOUND,
                "El usuario solicitado no existe.",
                404,
            )
        return user

    @staticmethod
    @transaction.atomic
    def create_bootstrap_admin(
        *,
        name,
        paternal_surname,
        maternal_surname,
        email,
        person_role_code,
        password,
    ):
        if not settings.DEBUG:
            raise UserServiceError(
                "BOOTSTRAP_DISABLED",
                "La creación inicial del administrador está deshabilitada.",
                403,
            )

        admin_role = UserRole.objects.select_for_update().get(
            code=UserRole.Code.ADMINISTRATOR
        )
        if User.objects.exists():
            raise UserServiceError(
                "BOOTSTRAP_ALREADY_COMPLETED",
                "El administrador inicial ya fue creado.",
                409,
            )

        normalized_email = email.strip().casefold()
        if Person.objects.filter(email__iexact=normalized_email).exists():
            raise UserServiceError(
                "EMAIL_ALREADY_EXISTS",
                "Ya existe una persona con este correo electrónico.",
                409,
            )

        try:
            person_role = PersonRole.objects.get(code=person_role_code)
        except PersonRole.DoesNotExist as exc:
            raise UserServiceError(
                "PERSON_ROLE_NOT_FOUND",
                "El rol de persona seleccionado no existe.",
                400,
            ) from exc

        try:
            username = UsernameService.generate(
                name,
                paternal_surname,
                maternal_surname,
            )
        except UsernameGenerationError as exc:
            raise UserServiceError(
                "USERNAME_GENERATION_FAILED",
                "No fue posible generar un nombre de usuario válido.",
                400,
            ) from exc

        person = Person.objects.create(
            name=name.strip(),
            paternal_surname=paternal_surname.strip(),
            maternal_surname=maternal_surname.strip(),
            email=normalized_email,
            person_role=person_role,
        )
        return User.objects.create_superuser(
            username=username,
            password=password,
            person=person,
            user_role=admin_role,
        )
