from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from usuarios.models import Invitation, Person, PersonRole, User, UserRole
from usuarios.services.password_reset_token_service import (
    PasswordResetTokenService,
)
from usuarios.services.invitation_token_service import InvitationTokenService


class UserSchemaTests(TestCase):
    def setUp(self):
        self.user_role = UserRole.objects.get(code=UserRole.Code.USER)
        self.person_role = PersonRole.objects.get(code=PersonRole.Code.STUDENT)

    def create_person(self, email="person@example.com"):
        return Person.objects.create(
            name="Carlos",
            paternal_surname="Perez",
            maternal_surname="Bravo",
            email=email,
            person_role=self.person_role,
        )

    def create_user(self, suffix="1", email="person@example.com"):
        person = self.create_person(email=email)
        return User.objects.create_user(
            username=f"CPB12345{suffix}",
            password="SecurePassword!934",
            person=person,
            user_role=self.user_role,
        )

    def test_seed_migration_creates_fixed_roles(self):
        self.assertSetEqual(
            set(UserRole.objects.values_list("code", flat=True)),
            {"ADMINISTRATOR", "USER"},
        )
        self.assertSetEqual(
            set(PersonRole.objects.values_list("code", flat=True)),
            {"STUDENT", "INTERN", "TEACHER", "ASSISTANT"},
        )
        self.assertEqual(
            dict(UserRole.objects.values_list("code", "name")),
            {"ADMINISTRATOR": "Administrador", "USER": "Usuario"},
        )
        self.assertEqual(
            dict(PersonRole.objects.values_list("code", "name")),
            {
                "STUDENT": "Estudiante",
                "INTERN": "Pasante",
                "TEACHER": "Docente",
                "ASSISTANT": "Auxiliar",
            },
        )

    def test_invitation_status_values_are_stored_in_spanish(self):
        self.assertEqual(Invitation.Status.PENDING, "PENDIENTE")
        self.assertEqual(Invitation.Status.CANCELLED, "CANCELADA")
        self.assertEqual(Invitation.Status.ACCEPTED, "ACEPTADA")
        self.assertEqual(Invitation.Status.EXPIRED, "EXPIRADA")

    def test_fixed_roles_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.user_role.delete()
        with self.assertRaises(ProtectedError):
            PersonRole.objects.filter(pk=self.person_role.pk).delete()

    def test_person_email_is_normalized_and_case_insensitive_unique(self):
        person = self.create_person(email="  Person@Example.COM ")
        self.assertEqual(person.email, "person@example.com")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_person(email="PERSON@example.com")

    def test_username_is_normalized_and_case_insensitive_unique(self):
        user = self.create_user()
        self.assertEqual(user.username, "CPB123451")

        other_person = self.create_person(email="other@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="cpb123451",
                password="SecurePassword!934",
                person=other_person,
                user_role=self.user_role,
            )

    def test_user_delete_is_logical_and_also_deletes_person_logically(self):
        user = self.create_user()
        person = user.person

        deleted_count, _ = user.delete()

        self.assertEqual(deleted_count, 1)
        user.refresh_from_db()
        person.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.deleted_at)
        self.assertIsNotNone(person.deleted_at)

    def test_deleted_user_cannot_remain_active(self):
        user = self.create_user()
        user.deleted_at = timezone.now()

        with self.assertRaises(IntegrityError), transaction.atomic():
            user.save(update_fields=["deleted_at"])

    def test_only_one_pending_invitation_per_email_is_allowed(self):
        inviter = self.create_user()
        Invitation.objects.create(
            email="guest@example.com",
            person_role=self.person_role,
            invited_by=inviter,
            token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(days=2),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Invitation.objects.create(
                email="GUEST@example.com",
                person_role=self.person_role,
                invited_by=inviter,
                token_hash="b" * 64,
                expires_at=timezone.now() + timedelta(days=2),
            )

    def test_invitation_delete_cancels_instead_of_removing(self):
        inviter = self.create_user()
        invitation = Invitation.objects.create(
            email="guest@example.com",
            person_role=self.person_role,
            invited_by=inviter,
            token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(days=2),
        )

        invitation.delete()

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.CANCELLED)
        self.assertIsNotNone(invitation.cancelled_at)

    def test_accepted_invitation_requires_user_and_acceptance_date(self):
        inviter = self.create_user()

        with self.assertRaises(IntegrityError), transaction.atomic():
            Invitation.objects.create(
                email="guest@example.com",
                person_role=self.person_role,
                invited_by=inviter,
                token_hash="a" * 64,
                status=Invitation.Status.ACCEPTED,
                expires_at=timezone.now() + timedelta(days=2),
            )


@override_settings(DEBUG=True)
class BootstrapAdminEndpointTests(APITestCase):
    def setUp(self):
        self.url = reverse("bootstrap-admin")
        self.payload = {
            "name": "Cárlos",
            "paternal_surname": "Pérez",
            "maternal_surname": "Bravo",
            "email": "ADMIN@Example.com",
            "person_role_code": "TEACHER",
            "password": "admin",
            "password_confirm": "admin",
        }

    def test_bootstrap_creates_person_and_superuser(self):
        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertRegex(response.data["username"], r"^CPB\d{6}$")
        self.assertEqual(response.data["email"], "admin@example.com")
        self.assertEqual(response.data["person_role"], "TEACHER")
        self.assertEqual(response.data["user_role"], "ADMINISTRATOR")
        self.assertTrue(response.data["is_active"])
        self.assertTrue(response.data["is_staff"])
        self.assertTrue(response.data["is_superuser"])

        user = User.objects.get(pk=response.data["id"])
        self.assertTrue(user.check_password("admin"))
        self.assertEqual(Person.objects.count(), 1)

    def test_bootstrap_can_only_run_once(self):
        first_response = self.client.post(self.url, self.payload, format="json")
        second_payload = {
            **self.payload,
            "email": "second@example.com",
        }
        second_response = self.client.post(self.url, second_payload, format="json")

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            second_response.data["code"],
            "BOOTSTRAP_ALREADY_COMPLETED",
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Person.objects.count(), 1)

    @override_settings(DEBUG=False)
    def test_bootstrap_is_disabled_outside_debug(self):
        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "BOOTSTRAP_DISABLED")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Person.objects.count(), 0)

    def test_bootstrap_validates_password_confirmation(self):
        response = self.client.post(
            self.url,
            {**self.payload, "password_confirm": "different"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertIn("password_confirm", response.data["errors"])
        self.assertEqual(User.objects.count(), 0)


class AuthenticationControllerTests(APITestCase):
    password = "SecurePassword!934"

    def setUp(self):
        person = Person.objects.create(
            name="Ana",
            paternal_surname="Lopez",
            maternal_surname="Mamani",
            email="ana@example.com",
            person_role=PersonRole.objects.get(code=PersonRole.Code.TEACHER),
        )
        self.user = User.objects.create_user(
            username="ALM123456",
            password=self.password,
            person=person,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
        )

    def login(self, username=None, password=None):
        return self.client.post(
            reverse("auth-login"),
            {
                "username": username or self.user.username,
                "password": password or self.password,
            },
            format="json",
        )

    def authenticate(self):
        response = self.login()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}"
        )
        return response.data["access"]

    def test_login_returns_access_token_without_refresh_token(self):
        response = self.login(username="alm123456")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertEqual(response.data["token_type"], "Bearer")
        self.assertEqual(response.data["expires_in"], 8 * 60 * 60)
        self.assertEqual(response.data["user"]["username"], "ALM123456")
        self.assertEqual(response.data["user"]["person"]["email"], "ana@example.com")
        self.assertEqual(response.data["user"]["user_role"]["code"], "USER")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login)

    def test_login_rejects_incorrect_credentials_and_inactive_users(self):
        wrong_password = self.login(password="incorrect")
        self.assertEqual(wrong_password.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(wrong_password.data["code"], "AUTH_INVALID_CREDENTIALS")

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        inactive = self.login()
        self.assertEqual(inactive.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(inactive.data["code"], "AUTH_INVALID_CREDENTIALS")

    def test_login_returns_standard_field_errors(self):
        response = self.client.post(
            reverse("auth-login"),
            {"username": "", "password": self.password},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "VALIDATION_ERROR")
        self.assertEqual(
            response.data["errors"]["username"],
            [
                {
                    "code": "blank",
                    "message": "El campo username no puede estar vacío.",
                }
            ],
        )

    def test_me_requires_authentication_and_returns_current_user(self):
        unauthenticated = self.client.get(reverse("auth-me"))
        self.assertEqual(unauthenticated.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(unauthenticated.data["code"], "AUTH_REQUIRED")

        self.authenticate()
        response = self.client.get(reverse("auth-me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.id)
        self.assertEqual(response.data["person"]["name"], "Ana")

    def test_logout_invalidates_the_access_token(self):
        self.authenticate()

        logout = self.client.post(reverse("auth-logout"))
        me = self.client.get(reverse("auth-me"))

        self.assertEqual(logout.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(me.data["code"], "AUTH_TOKEN_INVALIDATED")
        self.user.refresh_from_db()
        self.assertEqual(self.user.token_version, 2)

    def test_invalid_and_expired_tokens_use_distinct_errors(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid-token")
        invalid = self.client.get(reverse("auth-me"))

        expired_token = AccessToken.for_user(self.user)
        expired_token["token_version"] = self.user.token_version
        expired_token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {expired_token}")
        expired = self.client.get(reverse("auth-me"))

        self.assertEqual(invalid.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(invalid.data["code"], "AUTH_TOKEN_INVALID")
        self.assertEqual(expired.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(expired.data["code"], "AUTH_TOKEN_EXPIRED")


class UserListControllerTests(APITestCase):
    password = "SecurePassword!934"

    def setUp(self):
        self.student_role = PersonRole.objects.get(code=PersonRole.Code.STUDENT)
        self.teacher_role = PersonRole.objects.get(code=PersonRole.Code.TEACHER)
        self.admin = self.create_user(
            username="ADM123456",
            email="admin@example.com",
            person_role=self.teacher_role,
            user_role=UserRole.objects.get(code=UserRole.Code.ADMINISTRATOR),
            name="Admin",
        )
        self.normal_user = self.create_user(
            username="USR123456",
            email="user@example.com",
            person_role=self.student_role,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
            name="Normal",
        )

    def create_user(
        self,
        *,
        username,
        email,
        person_role,
        user_role,
        name,
        is_active=True,
    ):
        person = Person.objects.create(
            name=name,
            paternal_surname="Perez",
            maternal_surname="Mamani",
            email=email,
            person_role=person_role,
        )
        return User.objects.create_user(
            username=username,
            password=self.password,
            person=person,
            user_role=user_role,
            is_active=is_active,
        )

    def authenticate(self, user):
        token = AccessToken.for_user(user)
        token["token_version"] = user.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_only_administrator_can_list_users(self):
        unauthenticated = self.client.get(reverse("user-list"))
        self.assertEqual(unauthenticated.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(unauthenticated.data["code"], "AUTH_REQUIRED")

        self.authenticate(self.normal_user)
        forbidden = self.client.get(reverse("user-list"))
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.data["code"], "PERMISSION_DENIED")

    def test_administrator_lists_users_with_person_and_role_data(self):
        self.authenticate(self.admin)

        response = self.client.get(reverse("user-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        listed_user = next(
            item for item in response.data if item["id"] == self.normal_user.id
        )
        self.assertEqual(
            set(listed_user),
            {"id", "username", "person", "user_role", "is_active"},
        )
        self.assertEqual(listed_user["username"], "USR123456")
        self.assertTrue(listed_user["is_active"])
        self.assertEqual(
            listed_user["person"],
            {
                "id": self.normal_user.person.id,
                "name": "Normal",
                "paternal_surname": "Perez",
                "maternal_surname": "Mamani",
                "email": "user@example.com",
                "person_role": {
                    "id": self.student_role.id,
                    "code": "STUDENT",
                    "name": "Estudiante",
                },
            },
        )
        self.assertEqual(
            listed_user["user_role"],
            {
                "id": self.normal_user.user_role.id,
                "code": "USER",
                "name": "Usuario",
            },
        )

    def test_list_includes_suspended_users_but_not_logically_deleted_users(self):
        suspended = self.create_user(
            username="SUS123456",
            email="suspended@example.com",
            person_role=self.student_role,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
            name="Suspended",
            is_active=False,
        )
        deleted = self.create_user(
            username="DEL123456",
            email="deleted@example.com",
            person_role=self.student_role,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
            name="Deleted",
        )
        deleted.delete()
        self.authenticate(self.admin)

        response = self.client.get(reverse("user-list"))

        listed_ids = {item["id"] for item in response.data}
        self.assertIn(suspended.id, listed_ids)
        self.assertNotIn(deleted.id, listed_ids)
        suspended_data = next(
            item for item in response.data if item["id"] == suspended.id
        )
        self.assertFalse(suspended_data["is_active"])

    def test_administrator_gets_user_detail_with_creation_dates(self):
        self.authenticate(self.admin)

        response = self.client.get(
            reverse("user-detail", args=[self.normal_user.id])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "username",
                "person",
                "user_role",
                "is_active",
                "created_at",
            },
        )
        self.assertEqual(response.data["id"], self.normal_user.id)
        self.assertEqual(response.data["username"], "USR123456")
        self.assertTrue(response.data["is_active"])
        self.assertIsNotNone(response.data["created_at"])
        self.assertEqual(response.data["person"]["name"], "Normal")
        self.assertEqual(response.data["person"]["paternal_surname"], "Perez")
        self.assertEqual(response.data["person"]["maternal_surname"], "Mamani")
        self.assertEqual(response.data["person"]["email"], "user@example.com")
        self.assertIsNotNone(response.data["person"]["created_at"])
        self.assertEqual(
            response.data["person"]["person_role"]["code"],
            PersonRole.Code.STUDENT,
        )
        self.assertEqual(
            response.data["user_role"]["code"],
            UserRole.Code.USER,
        )

    def test_only_administrator_can_get_user_detail(self):
        unauthenticated = self.client.get(
            reverse("user-detail", args=[self.normal_user.id])
        )
        self.assertEqual(unauthenticated.status_code, status.HTTP_401_UNAUTHORIZED)

        self.authenticate(self.normal_user)
        forbidden = self.client.get(
            reverse("user-detail", args=[self.normal_user.id])
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.data["code"], "PERMISSION_DENIED")

    def test_get_user_detail_rejects_missing_and_logically_deleted_users(self):
        deleted = self.create_user(
            username="DEL654321",
            email="detail-deleted@example.com",
            person_role=self.student_role,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
            name="Deleted",
        )
        deleted.delete()
        self.authenticate(self.admin)

        missing = self.client.get(reverse("user-detail", args=[999999]))
        deleted_response = self.client.get(
            reverse("user-detail", args=[deleted.id])
        )

        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.data["code"], "USER_NOT_FOUND")
        self.assertEqual(deleted_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(deleted_response.data["code"], "USER_NOT_FOUND")

    def test_administrator_updates_user_roles_and_status(self):
        original_token_version = self.normal_user.token_version
        self.authenticate(self.admin)

        response = self.client.patch(
            reverse("user-detail", args=[self.normal_user.id]),
            {
                "person_role_code": PersonRole.Code.TEACHER,
                "user_role_code": UserRole.Code.ADMINISTRATOR,
                "is_active": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["person"]["person_role"]["code"],
            PersonRole.Code.TEACHER,
        )
        self.assertEqual(
            response.data["user_role"]["code"],
            UserRole.Code.ADMINISTRATOR,
        )
        self.assertFalse(response.data["is_active"])

        self.normal_user.refresh_from_db()
        self.normal_user.person.refresh_from_db()
        self.assertEqual(
            self.normal_user.person.person_role.code,
            PersonRole.Code.TEACHER,
        )
        self.assertEqual(
            self.normal_user.user_role.code,
            UserRole.Code.ADMINISTRATOR,
        )
        self.assertFalse(self.normal_user.is_active)
        self.assertEqual(
            self.normal_user.token_version,
            original_token_version + 1,
        )

    def test_update_is_partial_and_preserves_non_editable_fields(self):
        original_person = {
            "name": self.normal_user.person.name,
            "paternal_surname": self.normal_user.person.paternal_surname,
            "maternal_surname": self.normal_user.person.maternal_surname,
            "email": self.normal_user.person.email,
        }
        original_username = self.normal_user.username
        original_user_role = self.normal_user.user_role_id
        original_token_version = self.normal_user.token_version
        self.authenticate(self.admin)

        response = self.client.patch(
            reverse("user-detail", args=[self.normal_user.id]),
            {"person_role_code": PersonRole.Code.TEACHER},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.normal_user.refresh_from_db()
        self.normal_user.person.refresh_from_db()
        self.assertEqual(self.normal_user.username, original_username)
        self.assertEqual(self.normal_user.user_role_id, original_user_role)
        self.assertTrue(self.normal_user.is_active)
        self.assertEqual(
            self.normal_user.token_version,
            original_token_version,
        )
        self.assertEqual(
            {
                "name": self.normal_user.person.name,
                "paternal_surname": self.normal_user.person.paternal_surname,
                "maternal_surname": self.normal_user.person.maternal_surname,
                "email": self.normal_user.person.email,
            },
            original_person,
        )

    def test_update_rejects_empty_body_invalid_roles_and_unknown_fields(self):
        self.authenticate(self.admin)
        url = reverse("user-detail", args=[self.normal_user.id])

        empty = self.client.patch(url, {}, format="json")
        invalid_role = self.client.patch(
            url,
            {"user_role_code": "INVALID"},
            format="json",
        )
        unknown_only = self.client.patch(
            url,
            {"name": "Changed"},
            format="json",
        )

        self.assertEqual(empty.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", empty.data["errors"])
        self.assertEqual(invalid_role.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("user_role_code", invalid_role.data["errors"])
        self.assertEqual(unknown_only.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", unknown_only.data["errors"])

    def test_only_administrator_can_update_user(self):
        url = reverse("user-detail", args=[self.normal_user.id])
        payload = {"is_active": False}

        unauthenticated = self.client.patch(url, payload, format="json")
        self.assertEqual(unauthenticated.status_code, status.HTTP_401_UNAUTHORIZED)

        self.authenticate(self.normal_user)
        forbidden = self.client.patch(url, payload, format="json")
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.data["code"], "PERMISSION_DENIED")

    def test_update_rejects_missing_and_logically_deleted_users(self):
        deleted = self.create_user(
            username="DEL987654",
            email="update-deleted@example.com",
            person_role=self.student_role,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
            name="Deleted",
        )
        deleted.delete()
        self.authenticate(self.admin)
        payload = {"is_active": False}

        missing = self.client.patch(
            reverse("user-detail", args=[999999]),
            payload,
            format="json",
        )
        deleted_response = self.client.patch(
            reverse("user-detail", args=[deleted.id]),
            payload,
            format="json",
        )

        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.data["code"], "USER_NOT_FOUND")
        self.assertEqual(deleted_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(deleted_response.data["code"], "USER_NOT_FOUND")


class OwnProfileUpdateControllerTests(APITestCase):
    password = "SecurePassword!934"

    def setUp(self):
        self.person_role = PersonRole.objects.get(code=PersonRole.Code.STUDENT)
        self.user_role = UserRole.objects.get(code=UserRole.Code.USER)
        person = Person.objects.create(
            name="Carlos",
            paternal_surname="Perez",
            maternal_surname="Bravo",
            email="carlos@example.com",
            person_role=self.person_role,
        )
        self.user = User.objects.create_user(
            username="CPB145631",
            password=self.password,
            person=person,
            user_role=self.user_role,
        )
        self.url = reverse("user-profile-update")

    def authenticate(self):
        token = AccessToken.for_user(self.user)
        token["token_version"] = self.user.token_version
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_authenticated_user_updates_own_profile(self):
        self.authenticate()

        response = self.client.patch(
            self.url,
            {
                "name": "Carla",
                "paternal_surname": "Quispe",
                "maternal_surname": "Mamani",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.user.id)
        self.assertEqual(response.data["username"], "CPB145631")
        self.assertEqual(response.data["person"]["name"], "Carla")
        self.assertEqual(
            response.data["person"]["paternal_surname"],
            "Quispe",
        )
        self.assertEqual(
            response.data["person"]["maternal_surname"],
            "Mamani",
        )
        self.assertEqual(
            response.data["person"]["email"],
            "carlos@example.com",
        )
        self.assertEqual(
            response.data["person"]["person_role"]["code"],
            PersonRole.Code.STUDENT,
        )
        self.assertEqual(
            response.data["user_role"]["code"],
            UserRole.Code.USER,
        )
        self.assertTrue(response.data["is_active"])

    def test_profile_update_is_partial(self):
        self.authenticate()

        response = self.client.patch(
            self.url,
            {"name": "Carlota"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.person.refresh_from_db()
        self.assertEqual(self.user.person.name, "Carlota")
        self.assertEqual(self.user.person.paternal_surname, "Perez")
        self.assertEqual(self.user.person.maternal_surname, "Bravo")
        self.assertEqual(self.user.person.email, "carlos@example.com")

    def test_profile_update_requires_authentication(self):
        response = self.client.patch(
            self.url,
            {"name": "Changed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "AUTH_REQUIRED")

    def test_profile_update_rejects_empty_invalid_and_protected_fields(self):
        self.authenticate()

        empty = self.client.patch(self.url, {}, format="json")
        blank = self.client.patch(
            self.url,
            {"name": "   "},
            format="json",
        )
        protected = self.client.patch(
            self.url,
            {
                "email": "changed@example.com",
                "username": "CHANGED123456",
                "is_active": False,
                "user_role_code": "ADMINISTRATOR",
            },
            format="json",
        )

        self.assertEqual(empty.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", empty.data["errors"])
        self.assertEqual(blank.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", blank.data["errors"])
        self.assertEqual(protected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", protected.data["errors"])
        self.assertIn("username", protected.data["errors"])
        self.assertIn("is_active", protected.data["errors"])
        self.assertIn("user_role_code", protected.data["errors"])
        self.user.refresh_from_db()
        self.user.person.refresh_from_db()
        self.assertEqual(self.user.username, "CPB145631")
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.user_role, self.user_role)
        self.assertEqual(self.user.person.email, "carlos@example.com")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_RESET_CONFIRM_URL="http://frontend.test/password/reset",
)
class PasswordControllerTests(APITestCase):
    current_password = "SecurePassword!934"
    new_password = "CompletelyDifferent!842"

    def setUp(self):
        person = Person.objects.create(
            name="Maria",
            paternal_surname="Quispe",
            maternal_surname="Flores",
            email="maria@example.com",
            person_role=PersonRole.objects.get(code=PersonRole.Code.STUDENT),
        )
        self.user = User.objects.create_user(
            username="MQF654321",
            password=self.current_password,
            person=person,
            user_role=UserRole.objects.get(code=UserRole.Code.USER),
        )

    def authenticate(self):
        response = self.client.post(
            reverse("auth-login"),
            {
                "username": self.user.username,
                "password": self.current_password,
            },
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}"
        )
        return response.data["access"]

    def request_reset_token(self):
        response = self.client.post(
            reverse("auth-password-forgot"),
            {"email": self.user.person.email},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(len(mail.outbox), 1)
        reset_url = next(
            part
            for part in mail.outbox[0].body.split()
            if part.startswith("http://frontend.test/password/reset")
        )
        return parse_qs(urlparse(reset_url).query)["token"][0]

    def test_change_password_requires_authentication(self):
        response = self.client.post(
            reverse("auth-password-change"),
            {
                "current_password": self.current_password,
                "new_password": self.new_password,
                "new_password_confirm": self.new_password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "AUTH_REQUIRED")

    def test_change_password_rejects_incorrect_current_password(self):
        self.authenticate()
        response = self.client.post(
            reverse("auth-password-change"),
            {
                "current_password": "WrongPassword!123",
                "new_password": self.new_password,
                "new_password_confirm": self.new_password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["code"],
            "AUTH_CURRENT_PASSWORD_INCORRECT",
        )
        self.assertIn("current_password", response.data["errors"])

    def test_change_password_validates_confirmation_and_strength(self):
        self.authenticate()
        mismatch = self.client.post(
            reverse("auth-password-change"),
            {
                "current_password": self.current_password,
                "new_password": self.new_password,
                "new_password_confirm": "AnotherPassword!734",
            },
            format="json",
        )
        weak = self.client.post(
            reverse("auth-password-change"),
            {
                "current_password": self.current_password,
                "new_password": "123",
                "new_password_confirm": "123",
            },
            format="json",
        )

        self.assertEqual(mismatch.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(mismatch.data["code"], "VALIDATION_ERROR")
        self.assertEqual(
            mismatch.data["errors"]["new_password_confirm"][0]["code"],
            "password_mismatch",
        )
        self.assertEqual(weak.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(weak.data["code"], "VALIDATION_ERROR")
        self.assertIn("new_password", weak.data["errors"])

    def test_change_password_invalidates_existing_tokens(self):
        old_access = self.authenticate()
        response = self.client.post(
            reverse("auth-password-change"),
            {
                "current_password": self.current_password,
                "new_password": self.new_password,
                "new_password_confirm": self.new_password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        me = self.client.get(reverse("auth-me"))
        self.assertEqual(me.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(me.data["code"], "AUTH_TOKEN_INVALIDATED")

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertEqual(self.user.token_version, 2)

    def test_forgot_sends_email_without_revealing_account_existence(self):
        existing = self.client.post(
            reverse("auth-password-forgot"),
            {"email": "MARIA@EXAMPLE.COM"},
            format="json",
        )
        missing = self.client.post(
            reverse("auth-password-forgot"),
            {"email": "missing@example.com"},
            format="json",
        )

        self.assertEqual(existing.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(missing.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(existing.data, missing.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("http://frontend.test/password/reset?token=", mail.outbox[0].body)

    def test_forgot_does_not_send_email_for_inactive_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("auth-password-forgot"),
            {"email": self.user.person.email},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(len(mail.outbox), 0)

    def test_forgot_is_rate_limited_with_standard_error(self):
        cache.clear()
        try:
            responses = [
                self.client.post(
                    reverse("auth-password-forgot"),
                    {"email": "missing@example.com"},
                    format="json",
                )
                for _ in range(6)
            ]
        finally:
            cache.clear()

        self.assertTrue(
            all(
                response.status_code == status.HTTP_202_ACCEPTED
                for response in responses[:5]
            )
        )
        self.assertEqual(
            responses[5].status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        self.assertEqual(
            responses[5].data["code"],
            "RATE_LIMIT_EXCEEDED",
        )

    def test_confirm_resets_password_and_token_cannot_be_reused(self):
        token = self.request_reset_token()
        payload = {
            "token": token,
            "new_password": self.new_password,
            "new_password_confirm": self.new_password,
        }

        confirmed = self.client.post(
            reverse("auth-password-confirm"),
            payload,
            format="json",
        )
        reused = self.client.post(
            reverse("auth-password-confirm"),
            payload,
            format="json",
        )

        self.assertEqual(confirmed.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(reused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            reused.data["code"],
            "PASSWORD_RESET_TOKEN_INVALID",
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertEqual(self.user.token_version, 2)

    def test_confirm_accepts_encoded_token_copied_from_email_link(self):
        response = self.client.post(
            reverse("auth-password-forgot"),
            {"email": self.user.person.email},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        reset_url = next(
            part
            for part in mail.outbox[0].body.split()
            if part.startswith("http://frontend.test/password/reset")
        )
        encoded_token = reset_url.split("token=", 1)[1]
        self.assertIn("%3A", encoded_token)

        confirmed = self.client.post(
            reverse("auth-password-confirm"),
            {
                "token": encoded_token,
                "new_password": self.new_password,
                "new_password_confirm": self.new_password,
            },
            format="json",
        )

        self.assertEqual(confirmed.status_code, status.HTTP_204_NO_CONTENT)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))

    def test_confirm_rejects_invalid_and_expired_tokens(self):
        payload = {
            "token": "invalid-token",
            "new_password": self.new_password,
            "new_password_confirm": self.new_password,
        }
        invalid = self.client.post(
            reverse("auth-password-confirm"),
            payload,
            format="json",
        )

        token = PasswordResetTokenService.create(self.user)
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            expired = self.client.post(
                reverse("auth-password-confirm"),
                {**payload, "token": token},
                format="json",
            )

        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            invalid.data["code"],
            "PASSWORD_RESET_TOKEN_INVALID",
        )
        self.assertEqual(expired.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            expired.data["code"],
            "PASSWORD_RESET_TOKEN_EXPIRED",
        )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    INVITATION_ACCEPT_URL="http://frontend.test/invitations/accept",
    INVITATION_EXPIRATION_HOURS=48,
)
class InvitationCreateControllerTests(APITestCase):
    password = "SecurePassword!934"

    def setUp(self):
        self.person_role = PersonRole.objects.get(code=PersonRole.Code.STUDENT)
        self.admin = self.create_user(
            username="ADM123456",
            email="admin@example.com",
            user_role_code=UserRole.Code.ADMINISTRATOR,
        )
        self.normal_user = self.create_user(
            username="USR123456",
            email="user@example.com",
            user_role_code=UserRole.Code.USER,
        )
        self.payload = {
            "email": "GUEST@Example.com",
            "person_role_code": PersonRole.Code.STUDENT,
        }
        self.accept_payload = {
            "name": "Carlos",
            "paternal_surname": "Perez",
            "maternal_surname": "Bravo",
            "password": "NewSecurePassword!842",
            "password_confirm": "NewSecurePassword!842",
        }

    def create_user(self, *, username, email, user_role_code):
        person = Person.objects.create(
            name="Test",
            paternal_surname=username[:3],
            maternal_surname="User",
            email=email,
            person_role=self.person_role,
        )
        return User.objects.create_user(
            username=username,
            password=self.password,
            person=person,
            user_role=UserRole.objects.get(code=user_role_code),
        )

    def authenticate(self, user):
        response = self.client.post(
            reverse("auth-login"),
            {"username": user.username, "password": self.password},
            format="json",
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}"
        )

    def create_invitation_for_token(self, raw_token="valid-invitation-token"):
        return Invitation.objects.create(
            email="invited@example.com",
            person_role=self.person_role,
            invited_by=self.admin,
            token_hash=InvitationTokenService.hash(raw_token),
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_only_administrator_can_create_invitation(self):
        unauthenticated = self.client.post(
            reverse("invitation-create"),
            self.payload,
            format="json",
        )
        self.assertEqual(
            unauthenticated.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.authenticate(self.normal_user)
        forbidden = self.client.post(
            reverse("invitation-create"),
            self.payload,
            format="json",
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.data["code"], "PERMISSION_DENIED")
        self.assertEqual(Invitation.objects.count(), 0)

    def test_only_administrator_can_list_invitations(self):
        unauthenticated = self.client.get(reverse("invitation-create"))
        self.assertEqual(
            unauthenticated.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.authenticate(self.normal_user)
        forbidden = self.client.get(reverse("invitation-create"))
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.data["code"], "PERMISSION_DENIED")

    def test_administrator_lists_invitations_with_requested_fields(self):
        first = self.create_invitation_for_token("first-list-token")
        second = Invitation.objects.create(
            email="second@example.com",
            person_role=PersonRole.objects.get(code=PersonRole.Code.TEACHER),
            invited_by=self.admin,
            token_hash=InvitationTokenService.hash("second-list-token"),
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.authenticate(self.admin)

        response = self.client.get(reverse("invitation-create"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data],
            [second.id, first.id],
        )
        self.assertSetEqual(
            set(response.data[0]),
            {
                "id",
                "email",
                "person_role",
                "status",
                "invited_by",
                "created_at",
            },
        )
        self.assertEqual(response.data[0]["email"], "second@example.com")
        self.assertEqual(response.data[0]["person_role"]["name"], "Docente")
        self.assertEqual(response.data[0]["status"], "PENDIENTE")
        self.assertEqual(
            response.data[0]["invited_by"],
            {
                "id": self.admin.id,
                "username": self.admin.username,
                "full_name": "Test ADM User",
            },
        )
        self.assertIsNotNone(response.data[0]["created_at"])

    def test_list_marks_elapsed_pending_invitations_as_expired(self):
        invitation = self.create_invitation_for_token("elapsed-list-token")
        service_now = invitation.expires_at + timedelta(seconds=1)
        self.authenticate(self.admin)

        with patch(
            "usuarios.services.invitation_service.timezone.now",
            return_value=service_now,
        ):
            response = self.client.get(reverse("invitation-create"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["status"], "EXPIRADA")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.EXPIRED)

    def test_only_administrator_can_cancel_invitation(self):
        invitation = self.create_invitation_for_token("cancel-permission-token")

        unauthenticated = self.client.post(
            reverse("invitation-cancel", args=[invitation.id])
        )
        self.assertEqual(
            unauthenticated.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.authenticate(self.normal_user)
        forbidden = self.client.post(
            reverse("invitation-cancel", args=[invitation.id])
        )
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden.data["code"], "PERMISSION_DENIED")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.PENDING)

    def test_administrator_cancels_pending_invitation_logically(self):
        raw_token = "cancel-pending-token"
        invitation = self.create_invitation_for_token(raw_token)
        self.authenticate(self.admin)

        response = self.client.post(
            reverse("invitation-cancel", args=[invitation.id])
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(Invitation.objects.filter(pk=invitation.id).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.CANCELLED)
        self.assertIsNotNone(invitation.cancelled_at)

        self.client.credentials()
        validate = self.client.get(
            reverse("invitation-validate", kwargs={"token": raw_token})
        )
        self.assertEqual(validate.status_code, status.HTTP_410_GONE)
        self.assertEqual(validate.data["code"], "INVITATION_CANCELLED")

    def test_cancel_rejects_missing_and_already_cancelled_invitation(self):
        invitation = self.create_invitation_for_token("cancel-twice-token")
        invitation.delete()
        self.authenticate(self.admin)

        missing = self.client.post(reverse("invitation-cancel", args=[999999]))
        repeated = self.client.post(
            reverse("invitation-cancel", args=[invitation.id])
        )

        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.data["code"], "INVITATION_NOT_FOUND")
        self.assertEqual(repeated.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            repeated.data["code"],
            "INVITATION_ALREADY_CANCELLED",
        )

    def test_cancel_rejects_accepted_invitation(self):
        invitation = self.create_invitation_for_token("accepted-cancel-token")
        invitation.status = Invitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_user = self.normal_user
        invitation.save(
            update_fields=[
                "status",
                "accepted_at",
                "accepted_user",
                "updated_at",
            ]
        )
        self.authenticate(self.admin)

        response = self.client.post(
            reverse("invitation-cancel", args=[invitation.id])
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data["code"],
            "INVITATION_ALREADY_ACCEPTED",
        )

    def test_cancel_marks_elapsed_invitation_as_expired(self):
        invitation = self.create_invitation_for_token("elapsed-cancel-token")
        service_now = invitation.expires_at + timedelta(seconds=1)
        self.authenticate(self.admin)

        with patch(
            "usuarios.services.invitation_service.timezone.now",
            return_value=service_now,
        ):
            response = self.client.post(
                reverse("invitation-cancel", args=[invitation.id])
            )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "INVITATION_EXPIRED")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.EXPIRED)
        self.assertIsNone(invitation.cancelled_at)

    def test_administrator_creates_and_sends_invitation(self):
        self.authenticate(self.admin)
        before = timezone.now()

        response = self.client.post(
            reverse("invitation-create"),
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], "guest@example.com")
        self.assertEqual(response.data["status"], Invitation.Status.PENDING)
        self.assertEqual(
            response.data["person_role"]["code"],
            PersonRole.Code.STUDENT,
        )
        self.assertNotIn("token", response.data)
        self.assertNotIn("token_hash", response.data)

        invitation = Invitation.objects.get(pk=response.data["id"])
        self.assertEqual(invitation.invited_by, self.admin)
        self.assertGreaterEqual(
            invitation.expires_at,
            before + timedelta(hours=48),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["guest@example.com"])
        self.assertIn(
            "http://frontend.test/invitations/accept?token=",
            mail.outbox[0].body,
        )
        raw_token = mail.outbox[0].body.split(
            "Token para ingreso manual:\n",
            1,
        )[1].split()[0]
        self.assertEqual(
            invitation.token_hash,
            InvitationTokenService.hash(raw_token),
        )
        self.assertNotEqual(invitation.token_hash, raw_token)

    def test_pending_invitation_cannot_be_duplicated(self):
        self.authenticate(self.admin)
        first = self.client.post(
            reverse("invitation-create"),
            self.payload,
            format="json",
        )
        duplicate = self.client.post(
            reverse("invitation-create"),
            {**self.payload, "email": "guest@EXAMPLE.COM"},
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(duplicate.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            duplicate.data["code"],
            "INVITATION_ALREADY_PENDING",
        )
        self.assertEqual(Invitation.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_registered_email_cannot_be_invited(self):
        self.authenticate(self.admin)
        response = self.client.post(
            reverse("invitation-create"),
            {
                **self.payload,
                "email": self.normal_user.person.email,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data["code"],
            "INVITATION_EMAIL_ALREADY_REGISTERED",
        )
        self.assertEqual(Invitation.objects.count(), 0)

    @patch(
        "usuarios.services.invitation_service."
        "InvitationEmailService.send_invitation",
        side_effect=RuntimeError("SMTP unavailable"),
    )
    def test_email_failure_rolls_back_invitation(self, send_invitation):
        self.authenticate(self.admin)
        response = self.client.post(
            reverse("invitation-create"),
            self.payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            response.data["code"],
            "INVITATION_EMAIL_DELIVERY_FAILED",
        )
        self.assertEqual(Invitation.objects.count(), 0)
        send_invitation.assert_called_once()

    def test_expired_pending_invitation_is_replaced(self):
        old_invitation = Invitation.objects.create(
            email="guest@example.com",
            person_role=self.person_role,
            invited_by=self.admin,
            token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        service_now = timezone.now() + timedelta(hours=2)
        self.authenticate(self.admin)

        with patch(
            "usuarios.services.invitation_service.timezone.now",
            return_value=service_now,
        ):
            response = self.client.post(
                reverse("invitation-create"),
                self.payload,
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        old_invitation.refresh_from_db()
        self.assertEqual(old_invitation.status, Invitation.Status.EXPIRED)
        self.assertEqual(
            Invitation.objects.filter(status=Invitation.Status.PENDING).count(),
            1,
        )

    def test_validate_returns_pending_invitation_without_consuming_it(self):
        raw_token = "valid-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)

        first = self.client.get(
            reverse("invitation-validate", kwargs={"token": raw_token})
        )
        second = self.client.get(
            reverse("invitation-validate", kwargs={"token": raw_token})
        )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(first.data["valid"])
        self.assertEqual(
            first.data["invitation"]["email"],
            "invited@example.com",
        )
        self.assertEqual(
            first.data["invitation"]["person_role"]["code"],
            PersonRole.Code.STUDENT,
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.PENDING)

    def test_validate_rejects_unknown_token(self):
        response = self.client.get(
            reverse(
                "invitation-validate",
                kwargs={"token": "unknown-invitation-token"},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "INVITATION_TOKEN_INVALID")

    def test_validate_marks_expired_invitation(self):
        raw_token = "expired-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)
        service_now = invitation.expires_at + timedelta(seconds=1)

        with patch(
            "usuarios.services.invitation_service.timezone.now",
            return_value=service_now,
        ):
            response = self.client.get(
                reverse("invitation-validate", kwargs={"token": raw_token})
            )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "INVITATION_EXPIRED")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.EXPIRED)

    def test_validate_rejects_cancelled_invitation(self):
        raw_token = "cancelled-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)
        invitation.delete()

        response = self.client.get(
            reverse("invitation-validate", kwargs={"token": raw_token})
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "INVITATION_CANCELLED")

    def test_validate_rejects_accepted_invitation(self):
        raw_token = "accepted-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)
        invitation.status = Invitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_user = self.normal_user
        invitation.save(
            update_fields=[
                "status",
                "accepted_at",
                "accepted_user",
                "updated_at",
            ]
        )

        response = self.client.get(
            reverse("invitation-validate", kwargs={"token": raw_token})
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data["code"],
            "INVITATION_ALREADY_ACCEPTED",
        )

    def test_validate_then_accept_creates_person_and_normal_user(self):
        raw_token = "accept-valid-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)
        initial_person_count = Person.objects.count()

        validated = self.client.get(
            reverse("invitation-validate", kwargs={"token": raw_token})
        )
        accepted = self.client.post(
            reverse("invitation-accept", kwargs={"token": raw_token}),
            self.accept_payload,
            format="json",
        )

        self.assertEqual(validated.status_code, status.HTTP_200_OK)
        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)
        self.assertRegex(accepted.data["username"], r"^CPB\d{6}$")
        self.assertEqual(
            accepted.data["person"]["email"],
            invitation.email,
        )
        self.assertEqual(
            accepted.data["person"]["person_role"]["code"],
            PersonRole.Code.STUDENT,
        )
        self.assertEqual(accepted.data["user_role"]["code"], UserRole.Code.USER)
        self.assertEqual(accepted.data["user_role"]["name"], "Usuario")
        self.assertTrue(accepted.data["is_active"])
        self.assertFalse(accepted.data["is_staff"])
        self.assertFalse(accepted.data["is_superuser"])
        self.assertEqual(Person.objects.count(), initial_person_count + 1)

        created_user = User.objects.get(pk=accepted.data["id"])
        self.assertTrue(created_user.check_password(self.accept_payload["password"]))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_user, created_user)
        self.assertIsNotNone(invitation.accepted_at)

    def test_accept_cannot_reuse_invitation(self):
        raw_token = "single-use-invitation-token"
        self.create_invitation_for_token(raw_token)

        first = self.client.post(
            reverse("invitation-accept", kwargs={"token": raw_token}),
            self.accept_payload,
            format="json",
        )
        second = self.client.post(
            reverse("invitation-accept", kwargs={"token": raw_token}),
            self.accept_payload,
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            second.data["code"],
            "INVITATION_ALREADY_ACCEPTED",
        )
        self.assertEqual(
            Person.objects.filter(email="invited@example.com").count(),
            1,
        )

    def test_accept_validates_password_fields_without_creating_records(self):
        raw_token = "password-validation-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)

        mismatch = self.client.post(
            reverse("invitation-accept", kwargs={"token": raw_token}),
            {**self.accept_payload, "password_confirm": "DifferentPassword!72"},
            format="json",
        )
        weak = self.client.post(
            reverse("invitation-accept", kwargs={"token": raw_token}),
            {**self.accept_payload, "password": "123", "password_confirm": "123"},
            format="json",
        )

        self.assertEqual(mismatch.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", mismatch.data["errors"])
        self.assertEqual(weak.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", weak.data["errors"])
        self.assertFalse(Person.objects.filter(email=invitation.email).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.PENDING)

    def test_accept_revalidates_unknown_and_expired_tokens(self):
        unknown = self.client.post(
            reverse(
                "invitation-accept",
                kwargs={"token": "unknown-accept-token"},
            ),
            self.accept_payload,
            format="json",
        )

        raw_token = "expired-accept-token"
        invitation = self.create_invitation_for_token(raw_token)
        service_now = invitation.expires_at + timedelta(seconds=1)
        with patch(
            "usuarios.services.invitation_service.timezone.now",
            return_value=service_now,
        ):
            expired = self.client.post(
                reverse("invitation-accept", kwargs={"token": raw_token}),
                self.accept_payload,
                format="json",
            )

        self.assertEqual(unknown.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(unknown.data["code"], "INVITATION_TOKEN_INVALID")
        self.assertEqual(expired.status_code, status.HTTP_410_GONE)
        self.assertEqual(expired.data["code"], "INVITATION_EXPIRED")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.EXPIRED)

    def test_accept_rejects_email_registered_after_invitation(self):
        raw_token = "registered-email-invitation-token"
        invitation = self.create_invitation_for_token(raw_token)
        Person.objects.create(
            name="Existing",
            paternal_surname="Person",
            maternal_surname="Account",
            email=invitation.email,
            person_role=self.person_role,
        )

        response = self.client.post(
            reverse("invitation-accept", kwargs={"token": raw_token}),
            self.accept_payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data["code"],
            "INVITATION_EMAIL_ALREADY_REGISTERED",
        )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.PENDING)
