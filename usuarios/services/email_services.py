# usuarios/services/email_services.py
from django.conf import settings
from django.core.mail import send_mail
from usuarios.models import Persona, Invitacion

def enviar_invitacion_registro(receiver_email, host_user):
    """
    Crea una persona invitada, genera el token de invitación y envía el correo.
    Lanza un ValueError si el correo ya existe.
    """
    # 1. Verificar si ya existe
    if Persona.objects.filter(email=receiver_email).exists():
        raise ValueError("Ya existe una persona registrada o invitada con este email.")

    # 2. Crear la Persona (con un rol por defecto, ej. 2)
    # Suponiendo que el ID 2 es el rol que deseas asignar a los invitados
    new_guest = Persona.objects.create(email=receiver_email, rol_persona_id=2)

    # 3. Crear la Invitación
    invitacion = Invitacion.objects.create(
        persona=new_guest,
        usuario=host_user if host_user.is_authenticated else None
    )

    # 4. Enviar el correo
    frontend_url = 'http://localhost:3000/register'
    asunto = "Has sido invitado a nuestro sistema"
    mensaje = (
        f"¡Hola!\n\n"
        f"Has sido invitado a unirte a nuestro sistema.\n"
        f"Para completar tu registro, entra a nuestra página: {frontend_url}\n\n"
        f"Copia este Token: {invitacion.token} \n"
        f"Te servirá para poder crear tu cuenta.\n\n"
        f"¡Te esperamos!"
    )
    
    send_mail(asunto, mensaje, settings.DEFAULT_FROM_EMAIL, [receiver_email])
    
    return invitacion