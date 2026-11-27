"""scripts/verify_consistency.sql: passes on healthy data, and catches each kind of corruption."""
# ruff: noqa: S608
import asyncio
from pathlib import Path

import pytest

SQL = (Path(__file__).resolve().parents[4] / "scripts" / "verify_consistency.sql").read_text()


class _Rollback(Exception):
    """Raised on purpose to undo a deliberate corruption."""


async def _violations(db) -> dict[str, int]:
    rows = await db.fetch(SQL)
    return {row["check_name"]: row["violations"] for row in rows}


async def _after_corrupting(pool, *statements: str) -> dict[str, int]:
    """Applies `statements` inside a transaction, runs the checks, then rolls everything back."""
    result: dict[str, int] = {}
    try:
        async with pool.acquire() as conn, conn.transaction():
            for statement in statements:
                await conn.execute(statement)
            result = await _violations(conn)
            raise _Rollback
    except _Rollback:
        pass
    return result


@pytest.fixture
async def busy_system(new_account, transfer):
    """Realistic activity: deposits, concurrent transfers, an idempotent replay, a rejection."""
    alice, bob, carol = await new_account(10_000), await new_account(5_000), await new_account(0)
    await asyncio.gather(
        *[transfer(alice, bob.wallet_id, 10 + n) for n in range(15)],
        *[transfer(bob, carol.wallet_id, 5 + n) for n in range(15)],
        *[transfer(alice, carol.wallet_id, 7) for _ in range(5)],
    )
    await transfer(alice, bob.wallet_id, 100, key="same")
    await transfer(alice, bob.wallet_id, 100, key="same")  # replay: must not move money twice
    assert (await transfer(carol, alice.wallet_id, 10**9)).status_code == 422  # insufficient funds


async def test_a_healthy_system_has_no_violations(pool, busy_system):
    result = await _violations(pool)

    assert {name: bad for name, bad in result.items() if bad} == {}
    assert "ledger_sums_to_zero" in result
    assert "no_negative_user_balances" in result
    assert "info_counts" in result  # informational rows are present and always 0


async def test_an_empty_database_passes_too(pool):
    assert {n: bad for n, bad in (await _violations(pool)).items() if bad} == {}


USER = "kind = 'user' AND id = (SELECT id FROM wallets WHERE kind = 'user' ORDER BY id LIMIT 1)"
ONE_TRANSFER = "(SELECT id FROM transfers WHERE type = 'transfer' ORDER BY id LIMIT 1)"

CORRUPTIONS = {
    "wallet_balance_equals_ledger_sum": [f"UPDATE wallets SET balance = balance + 1 WHERE {USER}"],
    "all_balances_sum_to_zero": [f"UPDATE wallets SET balance = balance + 1 WHERE {USER}"],
    "no_negative_user_balances": [
        "ALTER TABLE wallets DROP CONSTRAINT wallets_balance_non_negative",
        f"UPDATE wallets SET balance = -5 WHERE {USER}",
    ],
    "transfer_entries_balanced": [
        f"""
        INSERT INTO ledger_entries (transfer_id, wallet_id, amount, balance_after)
        SELECT {ONE_TRANSFER}, w.id, 5, 5
        FROM wallets w
        WHERE w.kind = 'user'
          AND NOT EXISTS (SELECT 1 FROM ledger_entries le
                          WHERE le.transfer_id = {ONE_TRANSFER} AND le.wallet_id = w.id)
        LIMIT 1
        """
    ],
    "ledger_sums_to_zero": [
        f"""
        INSERT INTO ledger_entries (transfer_id, wallet_id, amount, balance_after)
        SELECT {ONE_TRANSFER}, w.id, 5, 5
        FROM wallets w
        WHERE w.kind = 'user'
          AND NOT EXISTS (SELECT 1 FROM ledger_entries le
                          WHERE le.transfer_id = {ONE_TRANSFER} AND le.wallet_id = w.id)
        LIMIT 1
        """
    ],
    "running_balance_consistent": [
        "ALTER TABLE ledger_entries DISABLE TRIGGER ledger_entries_append_only",
        "UPDATE ledger_entries SET balance_after = balance_after + 1 WHERE id = "
        "(SELECT min(id) FROM ledger_entries)",
    ],
    "money_conserved": [
        "ALTER TABLE transfers DISABLE TRIGGER transfers_append_only",
        "UPDATE transfers SET amount = amount + 1 "
        "WHERE id = (SELECT id FROM transfers WHERE type = 'deposit' LIMIT 1)",
    ],
    "idempotency_keys_complete": ["UPDATE idempotency_keys SET response_status = NULL"],
    "one_idempotency_key_per_user_transfer": [
        f"DELETE FROM idempotency_keys WHERE transfer_id = {ONE_TRANSFER}"
    ],
    "every_transfer_has_one_outbox_event": [
        "DELETE FROM outbox_events WHERE id = (SELECT id FROM outbox_events LIMIT 1)"
    ],
}


@pytest.mark.parametrize("check", sorted(CORRUPTIONS))
async def test_each_kind_of_corruption_is_caught(pool, busy_system, check):
    result = await _after_corrupting(pool, *CORRUPTIONS[check])

    assert result[check] >= 1, f"{check} did not notice the corruption: {result}"


async def test_the_corruptions_really_were_rolled_back(pool, busy_system):
    await _after_corrupting(pool, *CORRUPTIONS["no_negative_user_balances"])

    assert {n: bad for n, bad in (await _violations(pool)).items() if bad} == {}
