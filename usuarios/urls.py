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
    InvitationCancelView,
    InvitationListCreateView,
    InvitationValidateView,
)
from usuarios.views.user import (
    BootstrapAdminView,
    OwnProfileUpdateView,
    UserDetailView,
    UserListView,
)


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
        InvitationListCreateView.as_view(),
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
        "invitations/<int:invitation_id>/cancel/",
        InvitationCancelView.as_view(),
        name="invitation-cancel",
    ),
    path(
        "users/bootstrap-admin/",
        BootstrapAdminView.as_view(),
        name="bootstrap-admin",
    ),
    path("users/", UserListView.as_view(), name="user-list"),
    path(
        "users/me/",
        OwnProfileUpdateView.as_view(),
        name="user-profile-update",
    ),
    path(
        "users/<int:user_id>/",
        UserDetailView.as_view(),
        name="user-detail",
    ),
]
