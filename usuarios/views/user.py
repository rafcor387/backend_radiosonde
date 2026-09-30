from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.permissions import IsAdministrator
from usuarios.serializers.authentication import CurrentUserSerializer
from usuarios.serializers.user import (
    BootstrapAdminResponseSerializer,
    BootstrapAdminSerializer,
    OwnProfileUpdateSerializer,
    UserDetailSerializer,
    UserListQuerySerializer,
    UserPaginatedListSerializer,
    UserUpdateSerializer,
)
from usuarios.services.user_service import UserService


class UserListView(APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    @extend_schema(
        operation_id="users_list",
        parameters=[UserListQuerySerializer],
        responses={200: UserPaginatedListSerializer},
        summary="List users",
        tags=["Users"],
    )
    def get(self, request):
        query = UserListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        result = UserService.list_all(**query.validated_data)
        return Response(
            UserPaginatedListSerializer(result).data,
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

    @extend_schema(
        request=UserUpdateSerializer,
        responses={200: UserDetailSerializer},
        summary="Update a user's roles or status",
        tags=["Users"],
    )
    def patch(self, request, user_id):
        serializer = UserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = UserService.update(
            user_id=user_id,
            **serializer.validated_data,
        )
        return Response(
            UserDetailSerializer(user).data,
            status=status.HTTP_200_OK,
        )


class OwnProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=OwnProfileUpdateSerializer,
        responses={200: CurrentUserSerializer},
        summary="Update the current user's profile",
        tags=["Users"],
    )
    def patch(self, request):
        serializer = OwnProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = UserService.update_own_profile(
            current_user=request.user,
            **serializer.validated_data,
        )
        return Response(
            CurrentUserSerializer(user).data,
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
