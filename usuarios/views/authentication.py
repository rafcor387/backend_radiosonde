from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.serializers.authentication import (
    CurrentUserSerializer,
    LoginResponseSerializer,
    LoginSerializer,
)
from usuarios.services.authentication_service import AuthenticationService


class LoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(
        request=LoginSerializer,
        responses={200: LoginResponseSerializer},
        auth=[],
        summary="Log in",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AuthenticationService.login(**serializer.validated_data)
        return Response(
            {
                "access": session["access"],
                "token_type": "Bearer",
                "expires_in": session["expires_in"],
                "user": CurrentUserSerializer(session["user"]).data,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Session closed")},
        summary="Log out",
        tags=["Authentication"],
    )
    def post(self, request):
        AuthenticationService.logout(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CurrentUserSerializer},
        summary="Get the current user",
        tags=["Authentication"],
    )
    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)
