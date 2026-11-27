import asyncio
import os
import re
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.db import create_pool
from app.main import create_app
from app.migrate import run_migrations


async def _ensure_database(url: str) -> None:
    """Creates the test database if missing (CI starts Postgres without init.sql)."""
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise RuntimeError(f"Unsafe test database name: {name!r}")
    conn = await asyncpg.connect(urlunsplit(parts._replace(path="/postgres")))
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')  # noqa: S608 - name validated above
    finally:
        await conn.close()


async def _prepare(url: str) -> None:
    await _ensure_database(url)
    await run_migrations(url)


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("TEST_DATABASE_URL is not set. Run the tests with `make test`.")
    asyncio.run(_prepare(url))  # idempotent: only applies what is missing


@pytest.fixture
async def pool():
    pool = await create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5)
    await pool.execute("TRUNCATE users")  # every test starts from an empty table
    yield pool
    await pool.close()


@pytest.fixture
async def client(pool):
    app = create_app()
    app.state.pool = pool  # the lifespan does not run under ASGITransport, so set the pool here
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
