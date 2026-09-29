from datetime import timedelta
from urllib.parse import parse_qs, urlparse

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
