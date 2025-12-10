from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class ErrorCode:
    """Application-specific error codes"""
    # 400xx - Bad Request errors
    BAD_REQUEST = "40000"
    INVALID_INPUT = "40001"
    PASSWORDS_DO_NOT_MATCH = "40002"

    # 401xx - Authentication errors
    UNAUTHORIZED = "40100"
    INVALID_PASSWORD = "40101"
    ACCOUNT_DISABLED = "40102"
    INVALID_TOKEN = "40103"
    TOKEN_EXPIRED = "40104"
    INVALID_CURRENT_PASSWORD = "40105"

    # 403xx - Permission errors
    FORBIDDEN = "40300"
    PERMISSION_DENIED = "40301"

    # 404xx - Not Found errors
    NOT_FOUND = "40400"
    USER_NOT_FOUND = "40401"

    # 409xx - Conflict errors
    CONFLICT = "40900"
    EMAIL_ALREADY_EXISTS = "40901"
    USERNAME_ALREADY_EXISTS = "40902"

    # 422xx - Validation errors
    VALIDATION_ERROR = "42200"

    # 500xx - Server errors
    INTERNAL_SERVER_ERROR = "50000"


class BaseAPIException(APIException):
    error_code = ErrorCode.BAD_REQUEST

    def __init__(self, detail=None, error_code=None):
        super().__init__(detail)
        if error_code:
            self.error_code = error_code


class BadRequestException(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Bad request.'
    default_code = 'bad_request'
    error_code = ErrorCode.BAD_REQUEST


class UnauthorizedException(BaseAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Authentication required.'
    default_code = 'unauthorized'
    error_code = ErrorCode.UNAUTHORIZED


class ForbiddenException(BaseAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'Permission denied.'
    default_code = 'forbidden'
    error_code = ErrorCode.FORBIDDEN


class NotFoundException(BaseAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'Resource not found.'
    default_code = 'not_found'
    error_code = ErrorCode.NOT_FOUND


class ConflictException(BaseAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Resource already exists.'
    default_code = 'conflict'
    error_code = ErrorCode.CONFLICT


class ValidationException(BaseAPIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = 'Validation error.'
    default_code = 'validation_error'
    error_code = ErrorCode.VALIDATION_ERROR


class InternalServerException(BaseAPIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'Internal server error.'
    default_code = 'internal_server_error'
    error_code = ErrorCode.INTERNAL_SERVER_ERROR


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        error_code = getattr(exc, 'error_code', str(response.status_code) + "00")
        message = response.data.get('detail', response.data) if isinstance(response.data, dict) else response.data

        custom_response_data = {
            'success': False,
            'error': {
                'code': error_code,
                'message': message,
            },
            'data': None,
        }
        response.data = custom_response_data

    return response
