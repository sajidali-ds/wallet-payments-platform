from fastapi import Request
from fastapi.responses import JSONResponse

from app.metrics import APP_ERRORS


class AppError(Exception):
    """Business errors raised by services. One handler turns them into JSON responses."""

    status_code = 400
    code = "error"
    message = "Something went wrong"


class EmailAlreadyRegistered(AppError):
    status_code = 409
    code = "email_already_registered"
    message = "An account with this email already exists"


class InvalidCredentials(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "Incorrect email or password"  # same text whether the email exists or not


class AccountDisabled(AppError):
    status_code = 403
    code = "account_disabled"
    message = "This account has been disabled"


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Missing bearer token"


class InvalidToken(AppError):
    status_code = 401
    code = "invalid_token"
    message = "Invalid token"


class TokenExpired(AppError):
    status_code = 401
    code = "token_expired"
    message = "Token has expired"


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    APP_ERRORS.labels(code=exc.code, status=str(exc.status_code)).inc()
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=headers,
    )
