from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.dependencies import AdminDep, CurrentUserDep
from app.exceptions import AppError, app_error_handler


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)

    @app.get("/whoami")
    async def whoami(user: CurrentUserDep) -> dict[str, str]:
        return {"id": str(user.id), "role": user.role}

    @app.get("/admin-only")
    async def admin_only(user: AdminDep) -> dict[str, str]:
        return {"id": str(user.id)}

    return app


def _token(**overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "role": "user",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    } | overrides
    return jwt.encode(payload, get_settings().jwt_secret.get_secret_value(), algorithm="HS256")


async def _get(path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def test_valid_token_identifies_user():
    user_id = str(uuid4())
    response = await _get("/whoami", _token(sub=user_id, role="admin"))
    assert response.status_code == 200
    assert response.json() == {"id": user_id, "role": "admin"}


async def test_missing_token_is_401():
    response = await _get("/whoami")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_expired_token_is_401():
    expired = datetime.now(UTC) - timedelta(hours=1)
    response = await _get("/whoami", _token(exp=expired))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


@pytest.mark.parametrize(
    "token",
    [
        "not.a.jwt",
        jwt.encode({"sub": str(uuid4()), "role": "user"}, "w" * 40, algorithm="HS256"),  # wrong key
        jwt.encode(
            {"sub": str(uuid4()), "role": "admin", "iat": datetime.now(UTC),
             "exp": datetime.now(UTC) + timedelta(minutes=5)},
            None,
            algorithm="none",
        ),  # forged "alg: none" token claiming to be admin
    ],
)
async def test_invalid_tokens_are_401(token):
    response = await _get("/whoami", token)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_token_with_non_uuid_subject_is_401():
    assert (await _get("/whoami", _token(sub="not-a-uuid"))).status_code == 401


async def test_token_with_unknown_role_is_401():
    assert (await _get("/whoami", _token(role="superuser"))).status_code == 401


async def test_user_role_cannot_use_admin_route():
    response = await _get("/admin-only", _token(role="user"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_admin_role_can_use_admin_route():
    assert (await _get("/admin-only", _token(role="admin"))).status_code == 200
