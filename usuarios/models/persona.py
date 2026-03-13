from django.db import models
from .rol import RolPersona

class Persona(models.Model):
    nombres = models.CharField(max_length=100, blank=False, null=True)
    apellido_paterno = models.CharField(max_length=100, blank=False, null=True)
    apellido_materno = models.CharField(max_length=100, blank=False, null=True)
    email = models.EmailField(null=True, unique=True)
    rol_persona = models.ForeignKey(RolPersona, on_delete=models.PROTECT, null=False, blank=False)
    creation_date = models.DateTimeField(auto_now_add=True)
    delete_date = models.DateTimeField(null=True, blank=True)
    update_date = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'personas'