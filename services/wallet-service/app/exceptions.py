import math

from fastapi import Request
from fastapi.responses import JSONResponse

from app.metrics import APP_ERRORS


class AppError(Exception):
    status_code = 400
    code = "error"
    message = "Something went wrong"
    headers: dict[str, str] | None = None


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


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to do this"


class WalletNotFound(AppError):
    status_code = 404
    code = "wallet_not_found"
    message = "Wallet not found"


class WalletAlreadyExists(AppError):
    status_code = 409
    code = "wallet_already_exists"
    message = "You already have a wallet"


class InsufficientFunds(AppError):
    status_code = 422
    code = "insufficient_funds"
    message = "Insufficient funds"


class CannotTransferToSelf(AppError):
    status_code = 422
    code = "cannot_transfer_to_self"
    message = "You cannot transfer to your own wallet"


class IdempotencyKeyReused(AppError):
    status_code = 422
    code = "idempotency_key_reused"
    message = "This Idempotency-Key was already used with a different request"


class IdempotencyKeyInProgress(AppError):
    status_code = 409
    code = "idempotency_key_in_progress"
    message = "A request with this Idempotency-Key is still being processed; retry shortly"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests, slow down"

    def __init__(self, retry_after_ms: int) -> None:
        super().__init__(self.message)
        self.headers = {"Retry-After": str(max(1, math.ceil(retry_after_ms / 1000)))}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    APP_ERRORS.labels(code=exc.code, status=str(exc.status_code)).inc()
    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers=headers or None,
    )
