from django.contrib.auth.models import AbstractUser
from django.db import models

class RolUser(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class User(AbstractUser):
    # No agregamos campo email, usaremos 'username' como email
    rol_user = models.ForeignKey(RolUser, on_delete=models.SET_NULL, null=True)
    created = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.username



class RolPersona(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class Persona(models.Model):
    nombres = models.CharField(max_length=100)
    apellido_paterno = models.CharField(max_length=100)
    apellido_materno = models.CharField(max_length=100, blank=True, null=True)
    rol_persona = models.ForeignKey(RolPersona, on_delete=models.SET_NULL, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    email = models.EmailField(unique=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombres} {self.apellido_paterno}"
