from django.db import models

class RolUser(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self):
        return self.nombre
    
    class Meta:
        db_table = 'rol_user'

class RolPersona(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self):
        return self.nombre

    class Meta:
        db_table = 'rol_persona'