from django.urls import path
from .views import enviar_correo_api_view, LoginView , MeView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("api/auth/login/", LoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/me/", MeView.as_view(), name="me"), 
    path('api/enviar-correo/', enviar_correo_api_view, name='api_enviar_correo'),
]

