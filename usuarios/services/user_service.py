from django.conf import settings
from django.db import transaction
from django.db.models import Value
from django.db.models.functions import Concat

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
    PAGE_SIZE = 10

    @staticmethod
    def list_all(
        *,
        page=1,
        username=None,
        person_role=None,
        user_role=None,
        name=None,
        is_active=None,
    ):
        users = (
            User.objects.filter(
                deleted_at__isnull=True,
                person__deleted_at__isnull=True,
            )
            .select_related("person__person_role", "user_role")
            .order_by("id")
        )

        if username is not None:
            users = users.filter(username__icontains=username)
        if person_role is not None:
            users = users.filter(person__person_role__code=person_role)
        if user_role is not None:
            users = users.filter(user_role__code=user_role)
        if name is not None:
            users = users.annotate(
                full_name=Concat(
                    "person__name",
                    Value(" "),
                    "person__paternal_surname",
                    Value(" "),
                    "person__maternal_surname",
                )
            ).filter(full_name__icontains=name)
        if is_active is not None:
            users = users.filter(is_active=is_active)

        count = users.count()
        offset = (page - 1) * UserService.PAGE_SIZE
        items = users[offset : offset + UserService.PAGE_SIZE]
        return {"count": count, "items": items}

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
    def update(
        *,
        user_id,
        person_role_code=None,
        user_role_code=None,
        is_active=None,
    ):
        user = (
            User.objects.select_for_update()
            .filter(
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

        if person_role_code is not None:
            try:
                person_role = PersonRole.objects.get(code=person_role_code)
            except PersonRole.DoesNotExist as exc:
                raise UserServiceError(
                    ErrorCode.PERSON_ROLE_NOT_FOUND,
                    "El rol de persona seleccionado no existe.",
                    400,
                ) from exc

            if user.person.person_role_id != person_role.id:
                user.person.person_role = person_role
                user.person.save(update_fields=["person_role", "updated_at"])

        user_update_fields = []
        invalidate_tokens = False

        if user_role_code is not None:
            try:
                user_role = UserRole.objects.get(code=user_role_code)
            except UserRole.DoesNotExist as exc:
                raise UserServiceError(
                    ErrorCode.USER_ROLE_NOT_FOUND,
                    "El rol de usuario seleccionado no existe.",
                    400,
                ) from exc

            if user.user_role_id != user_role.id:
                user.user_role = user_role
                user_update_fields.append("user_role")
                invalidate_tokens = True

        if is_active is not None and user.is_active != is_active:
            user.is_active = is_active
            user_update_fields.append("is_active")
            invalidate_tokens = True

        if invalidate_tokens:
            user.token_version += 1
            user_update_fields.append("token_version")

        if user_update_fields:
            user_update_fields.append("updated_at")
            user.save(update_fields=user_update_fields)

        return user

    @staticmethod
    @transaction.atomic
    def update_own_profile(
        *,
        current_user,
        name=None,
        paternal_surname=None,
        maternal_surname=None,
    ):
        user = (
            User.objects.select_for_update()
            .filter(
                pk=current_user.pk,
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

        person = user.person
        update_fields = []
        editable_values = {
            "name": name,
            "paternal_surname": paternal_surname,
            "maternal_surname": maternal_surname,
        }
        for field, value in editable_values.items():
            if value is not None and getattr(person, field) != value:
                setattr(person, field, value.strip())
                update_fields.append(field)

        if update_fields:
            update_fields.append("updated_at")
            person.save(update_fields=update_fields)

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
                ErrorCode.EMAIL_ALREADY_EXISTS,
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
