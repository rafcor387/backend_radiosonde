from django.db import models
import uuid

class Invitacion(models.Model):
    class EstadoInvitacion(models.TextChoices):
        ENTREGADA = 'ENTREGADA', 'Entregada'
        ACEPTADA = 'ACEPTADA', 'Aceptada'
        IGNORADA = 'IGNORADA', 'Ignorada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    guest = models.OneToOneField('Persona', on_delete=models.CASCADE)
    host = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, related_name='invitaciones_enviadas')

    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    estado = models.CharField(max_length=10, choices=EstadoInvitacion.choices, default=EstadoInvitacion.ENTREGADA)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invitación para {self.guest.email} por {self.host.username if self.host else 'sistema'}"