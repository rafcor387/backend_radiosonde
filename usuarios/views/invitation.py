from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.permissions import IsAdministrator
from usuarios.serializers.invitation import (
    InvitationAcceptSerializer,
    InvitationCreateSerializer,
    InvitationListQuerySerializer,
    InvitationPaginatedListSerializer,
    InvitationResponseSerializer,
    InvitationValidationResponseSerializer,
)
from usuarios.serializers.authentication import CurrentUserSerializer
from usuarios.services.invitation_service import InvitationService


class InvitationListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]
    serializer_class = InvitationCreateSerializer

    @extend_schema(
        parameters=[InvitationListQuerySerializer],
        responses={200: InvitationPaginatedListSerializer},
        summary="List invitations",
        tags=["Invitations"],
    )
    def get(self, request):
        query = InvitationListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        result = InvitationService.list_all(**query.validated_data)
        return Response(
            InvitationPaginatedListSerializer(result).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=InvitationCreateSerializer,
        responses={201: InvitationResponseSerializer},
        summary="Create and send an invitation",
        tags=["Invitations"],
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = InvitationService.create_and_send(
            invited_by=request.user,
            **serializer.validated_data,
        )
        return Response(
            InvitationResponseSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


class InvitationValidateView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={200: InvitationValidationResponseSerializer},
        auth=[],
        summary="Validate an invitation",
        tags=["Invitations"],
    )
    def get(self, request, token):
        invitation = InvitationService.validate_token(raw_token=token)
        return Response(
            InvitationValidationResponseSerializer(
                {"valid": True, "invitation": invitation}
            ).data,
            status=status.HTTP_200_OK,
        )


class InvitationAcceptView(APIView):
    permission_classes = [AllowAny]
    serializer_class = InvitationAcceptSerializer

    @extend_schema(
        request=InvitationAcceptSerializer,
        responses={201: CurrentUserSerializer},
        auth=[],
        summary="Accept an invitation",
        tags=["Invitations"],
    )
    def post(self, request, token):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data.copy()
        data.pop("password_confirm")
        user = InvitationService.accept(raw_token=token, **data)
        return Response(
            CurrentUserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class InvitationCancelView(APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Invitation cancelled")},
        summary="Cancel a pending invitation",
        tags=["Invitations"],
    )
    def post(self, request, invitation_id):
        InvitationService.cancel(invitation_id=invitation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
