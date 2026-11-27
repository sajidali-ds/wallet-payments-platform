"""The database must refuse bad data on its own, even if the application code had a bug."""

from uuid import uuid4

import asyncpg
import pytest

from app.constants import SYSTEM_WALLET_ID


async def _user_wallet(pool) -> object:
    return await pool.fetchval(
        "INSERT INTO wallets (user_id, kind) VALUES ($1, 'user') RETURNING id", uuid4()
    )


async def _insert_transfer(conn, from_id, to_id, amount=100) -> object:
    return await conn.fetchval(
        """
        INSERT INTO transfers (type, from_wallet_id, to_wallet_id, amount, initiated_by)
        VALUES ('deposit', $1, $2, $3, $4) RETURNING id
        """,
        from_id,
        to_id,
        amount,
        uuid4(),
    )


_INSERT_ENTRY = """
    INSERT INTO ledger_entries (transfer_id, wallet_id, amount, balance_after)
    VALUES ($1, $2, $3, 0)
"""


async def _commit_balanced_transfer(pool, wallet_id, amount=100) -> object:
    async with pool.acquire() as conn, conn.transaction():
        transfer_id = await _insert_transfer(conn, SYSTEM_WALLET_ID, wallet_id, amount)
        await conn.execute(_INSERT_ENTRY, transfer_id, SYSTEM_WALLET_ID, -amount)
        await conn.execute(_INSERT_ENTRY, transfer_id, wallet_id, amount)
    return transfer_id


# ---- wallets ---------------------------------------------------------------------------------
async def test_system_wallet_is_seeded(pool):
    row = await pool.fetchrow(
        "SELECT kind, user_id, balance FROM wallets WHERE id = $1", SYSTEM_WALLET_ID
    )
    assert (row["kind"], row["user_id"], row["balance"]) == ("system", None, 0)


async def test_user_balance_cannot_go_negative(pool):
    wallet_id = await _user_wallet(pool)
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute("UPDATE wallets SET balance = -1 WHERE id = $1", wallet_id)


async def test_system_wallet_may_go_negative(pool):
    await pool.execute("UPDATE wallets SET balance = -500 WHERE id = $1", SYSTEM_WALLET_ID)
    balance = await pool.fetchval("SELECT balance FROM wallets WHERE id = $1", SYSTEM_WALLET_ID)
    assert balance == -500


async def test_one_wallet_per_user_and_currency(pool):
    user_id = uuid4()
    await pool.execute("INSERT INTO wallets (user_id, kind) VALUES ($1, 'user')", user_id)
    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute("INSERT INTO wallets (user_id, kind) VALUES ($1, 'user')", user_id)


async def test_user_wallet_must_have_an_owner(pool):
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute("INSERT INTO wallets (user_id, kind) VALUES (NULL, 'user')")


# ---- transfers -------------------------------------------------------------------------------
@pytest.mark.parametrize("amount", [0, -1])
async def test_transfer_amount_must_be_positive(pool, amount):
    wallet_id = await _user_wallet(pool)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_transfer(pool, SYSTEM_WALLET_ID, wallet_id, amount)


async def test_transfer_needs_two_different_wallets(pool):
    wallet_id = await _user_wallet(pool)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_transfer(pool, wallet_id, wallet_id)


async def test_transfers_are_immutable(pool):
    transfer_id = await _commit_balanced_transfer(pool, await _user_wallet(pool))
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute("UPDATE transfers SET amount = 1 WHERE id = $1", transfer_id)
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute("DELETE FROM transfers WHERE id = $1", transfer_id)


# ---- ledger ----------------------------------------------------------------------------------
async def test_balanced_ledger_entries_commit(pool):
    transfer_id = await _commit_balanced_transfer(pool, await _user_wallet(pool))
    count = await pool.fetchval(
        "SELECT count(*) FROM ledger_entries WHERE transfer_id = $1", transfer_id
    )
    assert count == 2


async def test_unbalanced_ledger_entries_are_rejected_at_commit(pool):
    wallet_id = await _user_wallet(pool)
    with pytest.raises(asyncpg.PostgresError):
        async with pool.acquire() as conn, conn.transaction():
            transfer_id = await _insert_transfer(conn, SYSTEM_WALLET_ID, wallet_id)
            await conn.execute(_INSERT_ENTRY, transfer_id, wallet_id, 100)  # no matching debit
    assert await pool.fetchval("SELECT count(*) FROM transfers") == 0  # everything rolled back


async def test_ledger_entries_are_immutable(pool):
    await _commit_balanced_transfer(pool, await _user_wallet(pool))
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute("UPDATE ledger_entries SET amount = amount + 1")
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute("DELETE FROM ledger_entries")


async def test_ledger_amount_cannot_be_zero(pool):
    wallet_id = await _user_wallet(pool)
    with pytest.raises(asyncpg.CheckViolationError):
        async with pool.acquire() as conn, conn.transaction():
            transfer_id = await _insert_transfer(conn, SYSTEM_WALLET_ID, wallet_id)
            await conn.execute(_INSERT_ENTRY, transfer_id, wallet_id, 0)


async def test_a_wallet_appears_once_per_transfer(pool):
    wallet_id = await _user_wallet(pool)
    with pytest.raises(asyncpg.UniqueViolationError):
        async with pool.acquire() as conn, conn.transaction():
            transfer_id = await _insert_transfer(conn, SYSTEM_WALLET_ID, wallet_id)
            await conn.execute(_INSERT_ENTRY, transfer_id, wallet_id, 100)
            await conn.execute(_INSERT_ENTRY, transfer_id, wallet_id, -100)


# ---- idempotency keys ------------------------------------------------------------------------
_INSERT_KEY = "INSERT INTO idempotency_keys (user_id, key, request_hash) VALUES ($1, $2, 'h')"


async def test_idempotency_key_is_unique_per_user(pool):
    user_id = uuid4()
    await pool.execute(_INSERT_KEY, user_id, "key-1")
    with pytest.raises(asyncpg.UniqueViolationError):
        await pool.execute(_INSERT_KEY, user_id, "key-1")


async def test_two_users_may_use_the_same_idempotency_key(pool):
    await pool.execute(_INSERT_KEY, uuid4(), "key-1")
    await pool.execute(_INSERT_KEY, uuid4(), "key-1")


async def test_idempotency_key_cannot_be_empty(pool):
    with pytest.raises(asyncpg.CheckViolationError):
        await pool.execute(_INSERT_KEY, uuid4(), "")
