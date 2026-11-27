import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import Settings


# ---- passwords -------------------------------------------------------------------------------
# bcrypt is deliberately slow (~250 ms). Run directly in an async endpoint it would freeze the
# whole event loop, so it goes to a worker thread via asyncio.to_thread.
def _hash_sync(password: str, rounds: int) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def _verify_sync(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


async def hash_password(password: str, rounds: int) -> str:
    return await asyncio.to_thread(_hash_sync, password, rounds)


async def verify_password(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(_verify_sync, password, password_hash)


_dummy_hash: str | None = None


async def get_dummy_hash(rounds: int) -> str:
    """A real bcrypt hash of a throwaway password.

    Login verifies against it when the email is unknown, so "unknown email" and "wrong password"
    take the same time. Otherwise response time would reveal which emails are registered.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password("not-a-real-password", rounds)
    return _dummy_hash


# ---- JWT -------------------------------------------------------------------------------------
def create_access_token(user_id: uuid.UUID, role: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "jti": uuid.uuid4().hex,
    }
    secret = settings.jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError.

    `algorithms` is always passed explicitly, so a forged token claiming alg "none" is rejected.
    """
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )
