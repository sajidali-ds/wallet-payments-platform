from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.cache.balance_cache import BalanceCache
from app.config import Settings, get_settings
from app.exceptions import (
    Forbidden,
    InvalidToken,
    NotAuthenticated,
    RateLimited,
    TokenExpired,
)
from app.metrics import RATE_LIMITED
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


async def require_admin(user: CurrentUserDep) -> CurrentUser:
    if user.role != "admin":
        raise Forbidden
    return user


AdminDep = Annotated[CurrentUser, Depends(require_admin)]


def get_balance_cache(request: Request) -> BalanceCache:
    return request.app.state.balance_cache


BalanceCacheDep = Annotated[BalanceCache, Depends(get_balance_cache)]


def limit_requests(scope: str, limit_attr: str):
    """Builds a dependency that rate-limits the caller PER USER (not per IP).

    It depends on CurrentUserDep, so authentication runs first: unauthenticated requests get a
    401 and cannot burn anyone's budget. `limit_attr` names a field of RateLimits, looked up at
    request time so the limit can be configured. Window: one minute.
    """

    async def enforce(request: Request, user: CurrentUserDep) -> None:
        limit = getattr(request.app.state.rate_limits, limit_attr)
        result = await request.app.state.rate_limiter.hit(
            f"{scope}:{user.id}", limit=limit, window_seconds=60
        )
        if not result.allowed:
            RATE_LIMITED.labels(scope=scope).inc()
            raise RateLimited(result.retry_after_ms)

    return enforce


limit_transfers = limit_requests("transfers", "transfers_per_minute")
limit_reads = limit_requests("reads", "reads_per_minute")
