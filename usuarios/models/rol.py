from django.db import models

class RolUser(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self):
        return self.nombre

class RolPersona(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self):
        return self.nombre