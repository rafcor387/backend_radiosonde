#models.py
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import uuid 

class CustomUserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('El campo username es obligatorio (usaremos el email).')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        admin_rol, _ = RolUser.objects.get_or_create(id=1, defaults={'nombre': 'Administrador'})
        extra_fields.setdefault('rol_user', admin_rol)
        return self.create_user(username, password, **extra_fields)

class RolUser(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self): return self.nombre

class RolPersona(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    def __str__(self): return self.nombre

class Persona(models.Model):
    nombres = models.CharField(max_length=100, blank=False, null=True)
    apellido_paterno = models.CharField(max_length=100, blank=False, null=True)
    apellido_materno = models.CharField(max_length=100, blank=False, null=True)
    email = models.EmailField(unique=True)
    rol_persona = models.ForeignKey(RolPersona, on_delete=models.PROTECT, null=False, blank=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.nombres:
            return f"{self.nombres} {self.apellido_paterno}"
        return self.email

class User(AbstractBaseUser, PermissionsMixin):
    username = models.EmailField(unique=True)
    rol_user = models.ForeignKey(RolUser, on_delete=models.SET_NULL, null=True, blank=True)
    
    persona = models.OneToOneField(Persona, on_delete=models.CASCADE, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    
    objects = CustomUserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.username

class Invitacion(models.Model):
    class EstadoInvitacion(models.TextChoices):
        ENTREGADA = 'ENTREGADA', 'Entregada'
        ACEPTADA = 'ACEPTADA', 'Aceptada'
        IGNORADA = 'IGNORADA', 'Ignorada'
        CANCELADA = 'CANCELADA', 'Cancelada'

    guest = models.OneToOneField(Persona, on_delete=models.CASCADE)
    
    host = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='invitaciones_enviadas')
    
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    
    estado = models.CharField(max_length=10, choices=EstadoInvitacion.choices, default=EstadoInvitacion.ENTREGADA)

    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invitación para {self.guest.email} por {self.host.username if self.host else 'sistema'}"