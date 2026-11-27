"""Velocity rule: more than 5 transfers within a minute gets flagged and logged, never blocked."""

import asyncio

import pytest

from app.services import fraud_service


async def _flags(pool):
    return await pool.fetch(
        """
        SELECT user_id::text AS user_id, rule, transfer_count, window_seconds,
               triggering_transfer_id::text AS transfer_id
        FROM fraud_flags ORDER BY created_at
        """
    )


async def _send(transfer, sender, receiver, count: int, amount: int = 10):
    responses = []
    for _ in range(count):
        responses.append(await transfer(sender, receiver.wallet_id, amount))
    return responses


async def test_five_transfers_are_fine_the_sixth_is_flagged_but_not_blocked(
    new_account, transfer, pool, balance_of
):
    alice, bob = await new_account(1000), await new_account()

    first_five = await _send(transfer, alice, bob, 5)
    assert [r.status_code for r in first_five] == [201] * 5
    assert await _flags(pool) == []  # five is allowed: the rule says "more than 5"

    sixth = await transfer(alice, bob.wallet_id, 10)

    assert sixth.status_code == 201  # flagged, NOT blocked
    assert await balance_of(bob) == 60  # the money moved
    flags = await _flags(pool)
    assert len(flags) == 1
    assert flags[0]["user_id"] == alice.user_id
    assert flags[0]["rule"] == "transfer_velocity"
    assert flags[0]["transfer_count"] == 6
    assert flags[0]["window_seconds"] == 60
    assert flags[0]["transfer_id"] == sixth.json()["transfer_id"]


async def test_one_flag_per_window_not_one_per_transfer(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()

    await _send(transfer, alice, bob, 9)

    assert len(await _flags(pool)) == 1  # transfers 7, 8 and 9 did not add flags


async def test_flag_is_logged(new_account, transfer, monkeypatch):
    class RecordingLog:
        def __init__(self) -> None:
            self.warnings: list[tuple[str, dict]] = []

        def warning(self, event: str, **fields) -> None:
            self.warnings.append((event, fields))

    recording = RecordingLog()
    monkeypatch.setattr(fraud_service, "log", recording)
    alice, bob = await new_account(1000), await new_account()

    await _send(transfer, alice, bob, 5)
    assert recording.warnings == []
    await transfer(alice, bob.wallet_id, 10)

    assert len(recording.warnings) == 1
    event, fields = recording.warnings[0]
    assert event == "fraud_flagged"
    assert fields["user_id"] == alice.user_id
    assert fields["transfer_count"] == 6


async def test_users_are_counted_separately(new_account, transfer, pool):
    alice, bob, carol = await new_account(1000), await new_account(1000), await new_account()

    await _send(transfer, alice, carol, 6)
    await _send(transfer, bob, carol, 3)

    flags = await _flags(pool)
    assert [f["user_id"] for f in flags] == [alice.user_id]


async def test_deposits_do_not_count(new_account, pool, client, headers_for):
    bob = await new_account()
    admin = headers_for(None, "admin")
    for _ in range(10):
        response = await client.post(
            f"/wallets/{bob.wallet_id}/deposit", json={"amount": 100}, headers=admin
        )
        assert response.status_code == 201
    assert await _flags(pool) == []


async def test_replayed_requests_do_not_count(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    for _ in range(10):
        await transfer(alice, bob.wallet_id, 10, key="same-key")  # one real transfer, nine replays
    assert await _flags(pool) == []


async def test_concurrent_transfers_are_counted_exactly(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()

    responses = await asyncio.gather(*[transfer(alice, bob.wallet_id, 10) for _ in range(12)])

    assert [r.status_code for r in responses] == [201] * 12
    flags = await _flags(pool)
    assert len(flags) == 1  # no duplicate flags, even under parallel requests
    assert flags[0]["transfer_count"] == 6  # flagged exactly when the 6th transfer committed


async def _insert_past_transfers(pool, sender, receiver, count: int, seconds_ago: float):
    """Raw rows (no ledger entries needed for the rule) with a chosen age."""
    for _ in range(count):
        await pool.execute(
            """
            INSERT INTO transfers
                (type, from_wallet_id, to_wallet_id, amount, initiated_by, created_at)
            VALUES ('transfer', $1, $2, 1, $3, now() - make_interval(secs => $4))
            """,
            sender.wallet_id,
            receiver.wallet_id,
            sender.user_id,
            seconds_ago,
        )


async def test_transfers_older_than_the_window_do_not_count(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await _insert_past_transfers(pool, alice, bob, 5, seconds_ago=120)  # two minutes ago

    await transfer(alice, bob.wallet_id, 10)

    assert await _flags(pool) == []


async def test_recent_transfers_inside_the_window_do_count(new_account, transfer, pool):
    alice, bob = await new_account(1000), await new_account()
    await _insert_past_transfers(pool, alice, bob, 5, seconds_ago=30)  # half a minute ago

    await transfer(alice, bob.wallet_id, 10)

    flags = await _flags(pool)
    assert [f["transfer_count"] for f in flags] == [6]


async def test_admin_can_list_flags(new_account, transfer, client, headers_for):
    alice, bob = await new_account(1000), await new_account()
    await _send(transfer, alice, bob, 6)

    response = await client.get("/admin/fraud-flags", headers=headers_for(None, "admin"))

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["user_id"] == alice.user_id
    assert items[0]["transfer_count"] == 6


@pytest.mark.parametrize("role", ["user"])
async def test_flags_are_admin_only(client, headers_for, role):
    as_user = await client.get("/admin/fraud-flags", headers=headers_for(None, role))
    assert as_user.status_code == 403
    assert (await client.get("/admin/fraud-flags")).status_code == 401
