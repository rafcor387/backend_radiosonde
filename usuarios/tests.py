from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from usuarios.models import Invitation, Person, PersonRole, User, UserRole


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
