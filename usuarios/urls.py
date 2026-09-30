from django.urls import path

from usuarios.views.authentication import (
    CurrentUserView,
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordConfirmView,
    PasswordForgotView,
)
from usuarios.views.invitation import (
    InvitationAcceptView,
    InvitationCreateView,
    InvitationValidateView,
)
from usuarios.views.user import BootstrapAdminView


urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/me/", CurrentUserView.as_view(), name="auth-me"),
    path(
        "auth/password/change/",
        PasswordChangeView.as_view(),
        name="auth-password-change",
    ),
    path(
        "auth/password/forgot/",
        PasswordForgotView.as_view(),
        name="auth-password-forgot",
    ),
    path(
        "auth/password/confirm/",
        PasswordConfirmView.as_view(),
        name="auth-password-confirm",
    ),
    path(
        "invitations/",
        InvitationCreateView.as_view(),
        name="invitation-create",
    ),
    path(
        "invitations/<str:token>/validate/",
        InvitationValidateView.as_view(),
        name="invitation-validate",
    ),
    path(
        "invitations/<str:token>/accept/",
        InvitationAcceptView.as_view(),
        name="invitation-accept",
    ),
    path(
        "users/bootstrap-admin/",
        BootstrapAdminView.as_view(),
        name="bootstrap-admin",
    ),
]
