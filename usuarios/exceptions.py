from rest_framework.exceptions import APIException

from usuarios.error_codes import ErrorCode


class ServiceError(APIException):
    def __init__(self, code, message, status_code, errors=None):
        self.error_code = code.value if isinstance(code, ErrorCode) else str(code)
        self.error_message = message
        self.status_code = status_code
        self.field_errors = errors or {}
        super().__init__(detail=message, code=self.error_code)


class InvalidCredentialsError(ServiceError):
    def __init__(self):
        super().__init__(
            ErrorCode.AUTH_INVALID_CREDENTIALS,
            "Credenciales incorrectas.",
            401,
        )
