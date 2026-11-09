from django.conf import settings
from django.core.mail import send_mail


class AccountEmailService:
    @staticmethod
    def send_account_created(user):
        send_mail(
            subject="Tu cuenta ha sido creada",
            message=(
                f"Hola {user.person.name},\n\n"
                "Tu cuenta en el Sistema de Radiosondeos LFA ha sido creada "
                "correctamente.\n\n"
                f"Tu nombre de usuario es: {user.username}\n\n"
                "Conserva este correo para recordar tu usuario. "
                "Puedes iniciar sesión con este usuario y la contraseña "
                "que elegiste durante el registro.\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.person.email],
            fail_silently=False,
        )
