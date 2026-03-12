from django.db import models
from .rol import RolPersona

class Persona(models.Model):
    nombres = models.CharField(max_length=100, blank=False, null=True)
    apellido_paterno = models.CharField(max_length=100, blank=False, null=True)
    apellido_materno = models.CharField(max_length=100, blank=False, null=True)
    email = models.EmailField(null=True, unique=True)
    rol_persona = models.ForeignKey(RolPersona, on_delete=models.PROTECT, null=False, blank=False)
    CreationDate = models.DateTimeField(auto_now_add=True)
    DeleteDate = models.DateTimeField(null=True, blank=True)
    UpdateDate = models.DateTimeField(null=True, blank=True)
   
    def __str__(self):
        if self.nombres:
            return f"{self.nombres} {self.apellido_paterno}"
        return self.email
    
    class Meta:
        db_table = 'persona'