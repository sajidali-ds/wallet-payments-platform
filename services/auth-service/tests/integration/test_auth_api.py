import asyncio
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings
from app.security import decode_access_token

EMAIL = "alice@example.com"
PASSWORD = "correct-horse-battery"


async def _register(client, email=EMAIL, password=PASSWORD):
    return await client.post("/auth/register", json={"email": email, "password": password})


async def _login(client, email=EMAIL, password=PASSWORD):
    return await client.post("/auth/login", json={"email": email, "password": password})


async def _token(client) -> str:
    await _register(client)
    return (await _login(client)).json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- register --------------------------------------------------------------------------------
async def test_register_success(client):
    response = await _register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "password" not in body
    assert "password_hash" not in body


async def test_register_stores_a_bcrypt_hash_not_the_password(client, pool):
    await _register(client)
    stored = await pool.fetchval("SELECT password_hash FROM users WHERE email = $1", EMAIL)
    assert stored != PASSWORD
    assert stored.startswith("$2")


async def test_register_duplicate_email_is_409_even_with_different_case(client):
    assert (await _register(client)).status_code == 201
    response = await _register(client, email="ALICE@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_already_registered"


async def test_concurrent_registrations_create_exactly_one_user(client, pool):
    # Both requests race past any "does it exist?" check; the UNIQUE constraint picks one winner.
    responses = await asyncio.gather(_register(client), _register(client))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert await pool.fetchval("SELECT count(*) FROM users") == 1


async def test_register_cannot_choose_a_role(client):
    response = await client.post(
        "/auth/register", json={"email": EMAIL, "password": PASSWORD, "role": "admin"}
    )
    assert response.status_code == 422


async def test_register_rejects_weak_password(client):
    assert (await _register(client, password="short")).status_code == 422


# ---- login -----------------------------------------------------------------------------------
async def test_login_returns_a_valid_token(client):
    user = (await _register(client)).json()
    response = await _login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().jwt_expire_minutes * 60

    claims = decode_access_token(body["access_token"], get_settings())
    assert claims["sub"] == user["id"]
    assert claims["role"] == "user"


async def test_login_wrong_password_and_unknown_email_look_identical(client):
    await _register(client)
    wrong_password = await _login(client, password="not-the-password")
    unknown_email = await _login(client, email="nobody@example.com")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_login_disabled_account_is_403(client, pool):
    await _register(client)
    await pool.execute("UPDATE users SET is_active = FALSE WHERE email = $1", EMAIL)
    response = await _login(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


# ---- /auth/me (exercises JWT verification) ---------------------------------------------------
async def test_me_with_valid_token(client):
    token = await _token(client)
    response = await client.get("/auth/me", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


async def test_me_without_token_is_401(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_me_with_garbage_token_is_401(client):
    response = await client.get("/auth/me", headers=_bearer("not.a.jwt"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_me_with_expired_token_is_401(client):
    user = (await _register(client)).json()
    now = datetime.now(UTC)
    expired = jwt.encode(
        {"sub": user["id"], "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        get_settings().jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    response = await client.get("/auth/me", headers=_bearer(expired))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


async def test_me_rejects_token_of_disabled_user(client, pool):
    token = await _token(client)
    await pool.execute("UPDATE users SET is_active = FALSE WHERE email = $1", EMAIL)
    response = await client.get("/auth/me", headers=_bearer(token))
    assert response.status_code == 401
