from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.config import get_settings
from app.security import create_access_token, decode_access_token, hash_password, verify_password


async def test_hash_and_verify_roundtrip():
    hashed = await hash_password("s3cret-pass", 4)
    assert hashed.startswith("$2")
    assert await verify_password("s3cret-pass", hashed)
    assert not await verify_password("wrong-pass", hashed)


async def test_same_password_gets_different_hashes():
    # bcrypt adds a random salt, so identical passwords never share a hash.
    assert await hash_password("s3cret-pass", 4) != await hash_password("s3cret-pass", 4)


def test_token_roundtrip():
    settings = get_settings()
    user_id = uuid4()
    claims = decode_access_token(create_access_token(user_id, "admin", settings), settings)
    assert claims["sub"] == str(user_id)
    assert claims["role"] == "admin"
    assert claims["exp"] > claims["iat"]


def _payload(**overrides):
    now = datetime.now(UTC)
    payload = {"sub": str(uuid4()), "iat": now, "exp": now + timedelta(minutes=5)}
    return payload | overrides


def test_expired_token_rejected():
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        _payload(exp=past), settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, settings)


def test_token_signed_with_other_secret_rejected():
    token = jwt.encode(_payload(), "x" * 40, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, get_settings())


def test_alg_none_token_rejected():
    token = jwt.encode(_payload(), None, algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, get_settings())


def test_token_without_exp_rejected():
    settings = get_settings()
    payload = {"sub": str(uuid4()), "iat": datetime.now(UTC)}
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, settings)
