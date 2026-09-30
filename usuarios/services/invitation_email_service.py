from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail


class InvitationEmailService:
    @staticmethod
    def send_invitation(invitation, raw_token):
        base_url = settings.INVITATION_ACCEPT_URL
        separator = "&" if "?" in base_url else "?"
        invitation_url = (
            f"{base_url}{separator}{urlencode({'token': raw_token})}"
        )

        send_mail(
            subject="Invitación para crear tu cuenta",
            message=(
                "Has recibido una invitación para crear una cuenta.\n\n"
                f"Rol asignado: {invitation.person_role.name}\n"
                f"Enlace de invitación: {invitation_url}\n\n"
                f"Token para ingreso manual:\n{raw_token}\n\n"
                f"La invitación vence el {invitation.expires_at.isoformat()}. "
                "Si no esperabas esta invitación, ignora este mensaje."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
