import asyncpg
import structlog

from app.config import Settings
from app.exceptions import AccountDisabled, EmailAlreadyRegistered, InvalidCredentials
from app.metrics import LOGINS, REGISTRATIONS
from app.repositories import user_repository
from app.security import create_access_token, get_dummy_hash, hash_password, verify_password

log = structlog.get_logger()


async def register_user(
    pool: asyncpg.Pool, settings: Settings, *, email: str, password: str
) -> asyncpg.Record:
    password_hash = await hash_password(password, settings.bcrypt_rounds)
    try:
        # No "SELECT first, then INSERT": two simultaneous requests could both pass the check.
        # We let the UNIQUE constraint decide, which is atomic.
        user = await user_repository.create_user(pool, email=email, password_hash=password_hash)
    except asyncpg.UniqueViolationError:
        raise EmailAlreadyRegistered from None
    REGISTRATIONS.inc()
    log.info("user_registered", user_id=str(user["id"]))  # user id, not email: keep PII out of logs
    return user


async def authenticate(pool: asyncpg.Pool, settings: Settings, *, email: str, password: str) -> str:
    """Returns a JWT access token, or raises InvalidCredentials / AccountDisabled."""
    user = await user_repository.get_by_email(pool, email)
    # Always run one bcrypt verification, even for unknown emails (see get_dummy_hash).
    stored_hash = user["password_hash"] if user else await get_dummy_hash(settings.bcrypt_rounds)
    password_ok = await verify_password(password, stored_hash)

    if user is None or not password_ok:
        LOGINS.labels(result="failed").inc()
        log.warning("login_failed")
        raise InvalidCredentials
    if not user["is_active"]:
        LOGINS.labels(result="disabled").inc()
        raise AccountDisabled

    LOGINS.labels(result="success").inc()
    log.info("login_succeeded", user_id=str(user["id"]))
    return create_access_token(user["id"], user["role"], settings)
