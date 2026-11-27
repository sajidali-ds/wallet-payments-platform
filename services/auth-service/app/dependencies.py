from typing import Annotated
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.exceptions import InvalidToken, NotAuthenticated, TokenExpired
from app.repositories import user_repository
from app.security import decode_access_token


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


PoolDep = Annotated[asyncpg.Pool, Depends(get_pool)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# auto_error=False: we raise our own 401 so every error has the same JSON shape.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    pool: PoolDep,
    settings: SettingsDep,
) -> asyncpg.Record:
    if credentials is None:
        raise NotAuthenticated
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except jwt.ExpiredSignatureError:  # must come first: it is a subclass of InvalidTokenError
        raise TokenExpired from None
    except jwt.InvalidTokenError:
        raise InvalidToken from None

    try:
        user_id = UUID(claims["sub"])
    except ValueError:
        raise InvalidToken from None

    user = await user_repository.get_by_id(pool, user_id)
    if user is None or not user["is_active"]:
        raise InvalidToken
    return user


CurrentUserDep = Annotated[asyncpg.Record, Depends(get_current_user)]
