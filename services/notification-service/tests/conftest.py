import asyncio
import inspect
import os
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest

# Set BEFORE any `app` module is imported: Settings is read from the environment and cached.
os.environ["JWT_SECRET"] = "test-secret-" + "k" * 40
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["RABBITMQ_URL"] = os.environ.get(
    "TEST_RABBITMQ_URL", "amqp://unused:unused@localhost:5672/"
)
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://unused:unused@localhost:5432/unused"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def headers_for():
    def make(user_id: UUID | None = None, role: str = "user") -> dict[str, str]:
        from app.config import get_settings

        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": str(user_id or uuid4()),
                "role": role,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            get_settings().jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def eventually():
    """await eventually(check): polls `check()` (sync or async) until it is truthy."""

    async def wait(check, timeout: float = 10.0, interval: float = 0.05):  # noqa: ASYNC109
        deadline = time.monotonic() + timeout
        while True:
            result = check()
            if inspect.isawaitable(result):
                result = await result
            if result:
                return result
            if time.monotonic() > deadline:
                raise AssertionError(f"condition not met within {timeout} seconds")
            await asyncio.sleep(interval)

    return wait
