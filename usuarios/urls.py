from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

# Importamos las vistas desde el paquete 'views' que creamos
from .views.auth import LoginView, CompletarRegistroUserView, EmailsendView
from .views.user import UserDetailView, UserMeView
from .views.persona import PersonaListCreateView, PersonaDetailView

urlpatterns = [
    #Tokens
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Auth & Emails & Registro
    path("auth/login/", LoginView.as_view(), name="login"),
    path('auth/enviar-correo/', EmailsendView.as_view(), name='api_enviar_correo'),
    path('auth/register-complete/', CompletarRegistroUserView.as_view(), name='register_complete'),

    # Usuarios (Gestión)
    path('users/', UserDetailView.as_view(), name='user_list_create'),
    path('users/<int:user_id>/', UserDetailView.as_view(), name='user_detail'),
    path("users/me/", UserMeView.as_view(), name="user_me"),

    # Personas (Gestión)
    path('persona/', PersonaListCreateView.as_view(), name='persona_list_create'),
    path('persona/<int:pk>/', PersonaDetailView.as_view(), name='persona_detail'),
]