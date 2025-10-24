from django.core.mail import send_mail
from django.conf import settings
import smtplib 
import os   
from dotenv import load_dotenv

load_dotenv()

def enviar_correo(receiver_email: str) -> bool:
    asunto = "Correo de Prueba desde Proyecto Django"
    mensaje = (
        f"¡Hola!\n\n"
        f"Has recibido este correo de prueba desde el endpoint de la API de Django.\n\n"
        f"¡El sistema de envío de correos funciona correctamente!\n\n"
        f"Destinatario: {receiver_email}"
    )
    remitente = settings.DEFAULT_FROM_EMAIL

    try:
        send_mail(asunto, mensaje, remitente, [receiver_email])
        print(f"Correo de prueba enviado exitosamente a {receiver_email}")
        return True
    except smtplib.SMTPException as e:
        print(f"Error al enviar el correo: {e}")
        return False
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")
        return False