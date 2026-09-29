import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken

from usuarios.error_codes import ErrorCode
from usuarios.exceptions import ServiceError


logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, ServiceError):
        return error_response(
            exc.error_code,
            exc.error_message,
            exc.status_code,
            exc.field_errors,
        )

    if isinstance(exc, ValidationError):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "Los datos enviados no son válidos.",
            status.HTTP_400_BAD_REQUEST,
            normalize_validation_errors(exc.detail),
        )

    if isinstance(exc, InvalidToken):
        if is_expired_token(exc.detail):
            return error_response(
                ErrorCode.AUTH_TOKEN_EXPIRED,
                "La sesión ha vencido.",
                status.HTTP_401_UNAUTHORIZED,
            )
        return error_response(
            ErrorCode.AUTH_TOKEN_INVALID,
            "El token de acceso no es válido.",
            status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, AuthenticationFailed):
        if exc.get_codes() == "token_invalidated":
            return error_response(
                ErrorCode.AUTH_TOKEN_INVALIDATED,
                "La sesión ya no es válida.",
                status.HTTP_401_UNAUTHORIZED,
            )
        return error_response(
            ErrorCode.AUTH_TOKEN_INVALID,
            "El token de acceso no es válido.",
            status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, NotAuthenticated):
        return error_response(
            ErrorCode.AUTH_REQUIRED,
            "Debe iniciar sesión para realizar esta acción.",
            status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "No tiene permiso para realizar esta acción.",
            status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, (NotFound, Http404)):
        return error_response(
            ErrorCode.NOT_FOUND,
            "El recurso solicitado no existe.",
            status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, MethodNotAllowed):
        return error_response(
            ErrorCode.METHOD_NOT_ALLOWED,
            "El método HTTP no está permitido para este recurso.",
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    if isinstance(exc, Throttled):
        return error_response(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            "Se realizaron demasiadas solicitudes. Intente nuevamente más tarde.",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        return error_response(
            ErrorCode.INTERNAL_ERROR,
            "No fue posible procesar la solicitud.",
            response.status_code,
        )

    logger.exception("Unhandled API error", exc_info=exc)
    return error_response(
        ErrorCode.INTERNAL_ERROR,
        "Ocurrió un error interno. Intente nuevamente más tarde.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def error_response(code, message, status_code, errors=None):
    code_value = code.value if isinstance(code, ErrorCode) else str(code)
    return Response(
        {
            "code": code_value,
            "message": message,
            "errors": errors or {},
        },
        status=status_code,
    )


def normalize_validation_errors(detail):
    normalized = {}

    def collect(value, path="non_field_errors"):
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = key if path == "non_field_errors" else f"{path}.{key}"
                collect(child, child_path)
            return
        if isinstance(value, (list, tuple)):
            for child in value:
                collect(child, path)
            return
        normalized.setdefault(path, []).append(
            {
                "code": getattr(value, "code", "invalid"),
                "message": str(value),
            }
        )

    collect(detail)
    return normalized


def is_expired_token(detail):
    if not isinstance(detail, dict):
        return "expired" in str(detail).lower()
    return any(
        "expired" in str(item.get("message", "")).lower()
        for item in detail.get("messages", [])
    )
