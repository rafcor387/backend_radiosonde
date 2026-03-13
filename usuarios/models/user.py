from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from .rol import RolUser

class CustomUserManager(BaseUserManager):
    #crear usuario normal
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('El campo username es obligatorio.')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    #crear usuario admin
    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        admin_rol, _ = RolUser.objects.get_or_create(id=1, defaults={'nombre': 'Administrador'})
        extra_fields.setdefault('rol_user', admin_rol)
        return self.create_user(username, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    username = models.EmailField(unique=True)
    rol_user = models.ForeignKey(RolUser, on_delete=models.SET_NULL, null=True, blank=True)

    # USAMOS 'Persona' (string) para evitar importar el archivo persona.py aquí
    persona = models.OneToOneField('Persona', on_delete=models.CASCADE, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    creation_date = models.DateTimeField(auto_now_add=True)
    delete_date = models.DateTimeField(null=True, blank=True)
    update_date = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'usuarios'