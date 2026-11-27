from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.exceptions import InvalidToken, NotAuthenticated, TokenExpired
from app.security import decode_access_token

VALID_ROLES = {"user", "admin"}


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


PoolDep = Annotated[asyncpg.Pool, Depends(get_pool)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    role: str


# Stateless auth: identity and role come from the signed token, with no call to auth-service.
# Trade-off: a user disabled in auth-service keeps working here until their token expires.
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: SettingsDep,
) -> CurrentUser:
    if credentials is None:
        raise NotAuthenticated
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except jwt.ExpiredSignatureError:  # first: it is a subclass of InvalidTokenError
        raise TokenExpired from None
    except jwt.InvalidTokenError:
        raise InvalidToken from None

    try:
        user_id = UUID(claims["sub"])
    except ValueError:
        raise InvalidToken from None
    role = claims.get("role")
    if role not in VALID_ROLES:
        raise InvalidToken
    return CurrentUser(id=user_id, role=role)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
