from django.urls import path
from . import views
from .views import EmailsendView, LoginView , MeView, UserDetailView, PersonaDetailView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/me/", MeView.as_view(), name="me"), 
    path('api/enviar-correo/', EmailsendView.as_view(), name='api_enviar_correo'),

    path('users/', UserDetailView.as_view(), name='user_list_create'),  
    path('users/<int:user_id>/', UserDetailView.as_view(), name='user_detail'),

    path('users/Persona/', PersonaDetailView.as_view(), name='persona_list_create'),  
    path('users/Persona/<int:persona_id>/', PersonaDetailView.as_view(), name='persona_detail'),
]
