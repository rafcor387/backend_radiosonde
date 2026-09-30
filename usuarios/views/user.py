from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.permissions import IsAdministrator
from usuarios.serializers.user import (
    BootstrapAdminResponseSerializer,
    BootstrapAdminSerializer,
    UserDetailSerializer,
    UserListSerializer,
)
from usuarios.services.user_service import UserService


class UserListView(APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    @extend_schema(
        responses={200: UserListSerializer(many=True)},
        summary="List users",
        tags=["Users"],
    )
    def get(self, request):
        users = UserService.list_all()
        return Response(
            UserListSerializer(users, many=True).data,
            status=status.HTTP_200_OK,
        )


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    @extend_schema(
        responses={200: UserDetailSerializer},
        summary="Get a user by ID",
        tags=["Users"],
    )
    def get(self, request, user_id):
        user = UserService.get_by_id(user_id=user_id)
        return Response(
            UserDetailSerializer(user).data,
            status=status.HTTP_200_OK,
        )


class BootstrapAdminView(APIView):
    permission_classes = [AllowAny]
    serializer_class = BootstrapAdminSerializer

    @extend_schema(
        request=BootstrapAdminSerializer,
        responses={
            201: BootstrapAdminResponseSerializer,
        },
        auth=[],
        summary="Create the initial administrator",
        description=(
            "Development-only, one-time endpoint. It is disabled after the first "
            "user is created."
        ),
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data.copy()
        data.pop("password_confirm")
        user = UserService.create_bootstrap_admin(**data)

        return Response(
            BootstrapAdminResponseSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )
