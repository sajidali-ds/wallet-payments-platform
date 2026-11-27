import asyncio
import contextlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.cache.balance_cache import BalanceCache
from app.cache.guard import RedisGuard
from app.cache.rate_limiter import RateLimiter
from app.db import create_pool
from app.main import create_app
from app.migrate import run_migrations


async def _ensure_database(url: str) -> None:
    """Creates the test database if missing (e.g. the Postgres volume predates it)."""
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
    asyncio.run(_prepare(url))


@pytest.fixture
async def pool():
    pool = await create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
    # TRUNCATE skips the append-only row triggers, so tests can start clean. The seeded system
    # wallet must survive: only user wallets are deleted, and its balance is reset.
    await pool.execute(
        "TRUNCATE idempotency_keys, ledger_entries, transfers, outbox_events, fraud_flags"
    )
    await pool.execute("DELETE FROM wallets WHERE kind = 'user'")
    await pool.execute("UPDATE wallets SET balance = 0 WHERE kind = 'system'")
    yield pool
    await pool.close()


@pytest.fixture
def make_client(pool):
    """make(cache=, limiter=, rate_limits=, redis=): an HTTP client on a fresh app.

    By default the cache and the rate limiter are DISABLED (redis=None), so the many tests that
    do 100 parallel transfers from one user are not throttled. Tests of the Redis features pass
    real (or deliberately broken) ones.
    """

    @contextlib.asynccontextmanager
    async def make(*, cache=None, limiter=None, rate_limits=None, redis=None):
        app = create_app()
        app.state.pool = pool  # no lifespan under ASGITransport, so plug things in directly
        app.state.balance_cache = cache or BalanceCache(None)
        app.state.rate_limiter = limiter or RateLimiter(None)
        app.state.redis = redis
        if rate_limits is not None:
            app.state.rate_limits = rate_limits
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    return make


@pytest.fixture
async def client(make_client):
    async with make_client() as client:
        yield client


# ---- Redis -----------------------------------------------------------------------------------
@pytest.fixture
async def redis_client():
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        raise RuntimeError("TEST_REDIS_URL is not set. Run the tests with `make test`.")
    client = Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25
    )
    await client.flushdb()  # tests use Redis database 15, never your dev data in database 0
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def broken_redis():
    """A Redis client pointing at a port where nothing listens: every call fails immediately."""
    client = Redis.from_url(
        "redis://127.0.0.1:1/0",
        decode_responses=True,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )
    yield client
    await client.aclose()


@pytest.fixture
def balance_cache(redis_client):
    return BalanceCache(redis_client, RedisGuard(), ttl_seconds=60)


@pytest.fixture
def limiter(redis_client):
    return RateLimiter(redis_client, RedisGuard())


@pytest.fixture
def assert_ledger_consistent(pool):
    """Checks the core accounting invariants. Call it at the end of any test that moves money."""

    async def check() -> None:
        mismatched = await pool.fetch(
            """
            SELECT w.id
            FROM wallets w
            LEFT JOIN ledger_entries le ON le.wallet_id = w.id
            GROUP BY w.id, w.balance
            HAVING w.balance <> COALESCE(SUM(le.amount), 0)
            """
        )
        assert mismatched == [], "wallet.balance differs from the sum of its ledger entries"

        unbalanced = await pool.fetch(
            "SELECT transfer_id FROM ledger_entries GROUP BY transfer_id HAVING SUM(amount) <> 0"
        )
        assert unbalanced == [], "a transfer's entries do not sum to zero"

        assert await pool.fetchval("SELECT COALESCE(SUM(balance), 0) FROM wallets") == 0, (
            "money was created or destroyed: all balances together must sum to zero"
        )

    return check


# ---- helpers for money-moving tests ----------------------------------------------------------
@dataclass(frozen=True)
class Account:
    headers: dict[str, str]  # Authorization header of the wallet's owner
    wallet_id: str
    user_id: str


@pytest.fixture
def new_account(client, headers_for):
    """Creates a user with a wallet, optionally funded through the admin deposit endpoint."""

    async def create(balance: int = 0) -> Account:
        user_id = uuid4()
        headers = headers_for(user_id)
        wallet_id = (await client.post("/wallets", headers=headers)).json()["id"]
        if balance:
            admin = headers_for(uuid4(), "admin")
            response = await client.post(
                f"/wallets/{wallet_id}/deposit", json={"amount": balance}, headers=admin
            )
            assert response.status_code == 201
        return Account(headers=headers, wallet_id=wallet_id, user_id=str(user_id))

    return create


@pytest.fixture
def transfer(client):
    """send(sender, to_wallet_id, amount, key=None, request_id=None): POST /transfers."""

    async def send(
        sender: Account,
        to_wallet_id: str,
        amount,
        key: str | None = None,
        request_id: str | None = None,
    ):
        headers = {**sender.headers, "Idempotency-Key": key or str(uuid4())}
        if request_id is not None:
            headers["X-Request-ID"] = request_id
        return await client.post(
            "/transfers", json={"to_wallet_id": to_wallet_id, "amount": amount}, headers=headers
        )

    return send


@pytest.fixture
def balance_of(pool):
    async def get(account: Account) -> int:
        return await pool.fetchval("SELECT balance FROM wallets WHERE id = $1", account.wallet_id)

    return get


@pytest.fixture
def rabbit_url() -> str:
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        raise RuntimeError("TEST_RABBITMQ_URL is not set. Run the tests with `make test`.")
    return url
