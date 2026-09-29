from django.urls import path

from usuarios.views.authentication import CurrentUserView, LoginView, LogoutView
from usuarios.views.user import BootstrapAdminView


urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", CurrentUserView.as_view(), name="auth-me"),
    path(
        "users/bootstrap-admin/",
        BootstrapAdminView.as_view(),
        name="bootstrap-admin",
    ),
]
