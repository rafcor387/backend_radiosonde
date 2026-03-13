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
    creation_date = models.DateTimeField(auto_now_add=True)
    delete_date = models.DateTimeField(null=True, blank=True)
    update_date = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'invitacion'
