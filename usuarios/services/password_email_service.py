from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail


class PasswordEmailService:
    @staticmethod
    def send_reset_email(user, token):
        base_url = settings.PASSWORD_RESET_CONFIRM_URL
        separator = "&" if "?" in base_url else "?"
        reset_url = f"{base_url}{separator}{urlencode({'token': token})}"
        timeout_minutes = max(1, settings.PASSWORD_RESET_TIMEOUT // 60)

        send_mail(
            subject="Restablecimiento de contraseña",
            message=(
                f"Hola {user.person.name},\n\n"
                "Se solicitó restablecer la contraseña de tu cuenta.\n"
                f"Utiliza el siguiente enlace: {reset_url}\n\n"
                f"Token para ingreso manual:\n{token}\n\n"
                f"El enlace vence en {timeout_minutes} minutos. "
                "Si no realizaste esta solicitud, ignora este mensaje."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.person.email],
            fail_silently=False,
        )
