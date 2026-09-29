from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from usuarios.serializers.authentication import (
    CurrentUserSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    MessageResponseSerializer,
    PasswordChangeSerializer,
    PasswordConfirmSerializer,
    PasswordForgotSerializer,
)
from usuarios.services.authentication_service import AuthenticationService
from usuarios.services.password_service import PasswordService


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


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    @extend_schema(
        request=PasswordChangeSerializer,
        responses={204: OpenApiResponse(description="Password changed")},
        summary="Change password",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        PasswordService.change_password(
            user=request.user,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordForgotView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordForgotSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_forgot"

    @extend_schema(
        request=PasswordForgotSerializer,
        responses={202: MessageResponseSerializer},
        auth=[],
        summary="Request a password reset",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        PasswordService.request_reset(email=serializer.validated_data["email"])
        return Response(
            {"message": PasswordService.forgot_response_message},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordConfirmView(APIView):
    permission_classes = [AllowAny]
    serializer_class = PasswordConfirmSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_confirm"

    @extend_schema(
        request=PasswordConfirmSerializer,
        responses={204: OpenApiResponse(description="Password reset")},
        auth=[],
        summary="Confirm a password reset",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        PasswordService.confirm_reset(
            token=serializer.validated_data["token"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
