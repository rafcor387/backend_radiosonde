from django.urls import path

from usuarios.views.user import BootstrapAdminView


urlpatterns = [
    path(
        "users/bootstrap-admin/",
        BootstrapAdminView.as_view(),
        name="bootstrap-admin",
    ),
]
