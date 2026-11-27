from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

BCRYPT_MAX_BYTES = 72  # bcrypt only uses the first 72 BYTES of a password


def _fits_bcrypt(value: str) -> str:
    # max_length counts characters, but bcrypt counts bytes ("é" is 2 bytes), so check both.
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"password must be at most {BCRYPT_MAX_BYTES} bytes")
    return value


def _lowercase(value: str) -> str:
    return value.lower()


Email = Annotated[EmailStr, AfterValidator(_lowercase)]
NewPassword = Annotated[str, Field(min_length=8, max_length=72), AfterValidator(_fits_bcrypt)]
LoginPassword = Annotated[str, Field(min_length=1, max_length=72), AfterValidator(_fits_bcrypt)]


class RegisterRequest(BaseModel):
    # forbid: unknown fields (e.g. "role": "admin") are rejected, not silently ignored.
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: NewPassword


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: LoginPassword


class UserResponse(BaseModel):
    # No password_hash field: a response model is an allow-list of what may leave the service.
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer" # noqa: S105
    expires_in: int  # seconds
