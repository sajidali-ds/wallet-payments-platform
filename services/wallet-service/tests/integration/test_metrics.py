import pytest
from prometheus_client import REGISTRY

from app.outbox.relay import OutboxRelay
from app.repositories import outbox_repository


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_committed_transfers_and_their_volume_are_counted(new_account, transfer):
    alice, bob = await new_account(1000), await new_account()
    count_before = sample("wallet_transfers_total", type="transfer")
    amount_before = sample("wallet_transfer_amount_paise_total", type="transfer")

    await transfer(alice, bob.wallet_id, 400)
    await transfer(alice, bob.wallet_id, 300)

    assert sample("wallet_transfers_total", type="transfer") - count_before == 2
    assert sample("wallet_transfer_amount_paise_total", type="transfer") - amount_before == 700


async def test_deposits_are_counted_under_their_own_type(new_account):
    before = sample("wallet_transfers_total", type="deposit")
    amount_before = sample("wallet_transfer_amount_paise_total", type="deposit")

    await new_account(2500)  # funding goes through the admin deposit endpoint

    assert sample("wallet_transfers_total", type="deposit") - before == 1
    assert sample("wallet_transfer_amount_paise_total", type="deposit") - amount_before == 2500


async def test_rejected_transfers_are_not_counted_as_transfers_but_as_errors(new_account, transfer):
    alice, bob = await new_account(100), await new_account()
    transfers_before = sample("wallet_transfers_total", type="transfer")
    errors = {"code": "insufficient_funds", "status": "422"}
    errors_before = sample("app_errors_total", **errors)

    assert (await transfer(alice, bob.wallet_id, 101)).status_code == 422

    assert sample("wallet_transfers_total", type="transfer") == transfers_before
    assert sample("app_errors_total", **errors) - errors_before == 1


async def test_replays_are_counted_but_do_not_count_as_new_transfers(new_account, transfer):
    alice, bob = await new_account(1000), await new_account()
    replays_before = sample("wallet_idempotent_replays_total")
    transfers_before = sample("wallet_transfers_total", type="transfer")

    await transfer(alice, bob.wallet_id, 100, key="k")
    await transfer(alice, bob.wallet_id, 100, key="k")

    assert sample("wallet_idempotent_replays_total") - replays_before == 1
    assert sample("wallet_transfers_total", type="transfer") - transfers_before == 1


async def test_http_metrics_use_route_templates(client, new_account):
    labels = {"method": "POST", "route": "/wallets/{wallet_id}/deposit", "status": "201"}
    before = sample("http_requests_total", **labels)

    account = await new_account(100)  # one deposit request

    assert sample("http_requests_total", **labels) - before == 1
    raw_path = f"/wallets/{account.wallet_id}/deposit"
    assert (
        REGISTRY.get_sample_value(
            "http_requests_total", {"method": "POST", "route": raw_path, "status": "201"}
        )
        is None
    )


async def test_outbox_backlog_gauge_follows_the_unpublished_events(client, pool):
    await pool.execute("DELETE FROM outbox_events")
    for n in range(3):
        await outbox_repository.add_event(pool, "transfer.completed", {"n": n})

    response = await client.get("/metrics")  # a scrape refreshes the gauges
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert sample("wallet_outbox_backlog") == 3
    assert sample("wallet_outbox_oldest_unpublished_age_seconds") >= 0

    class SilentBroker:
        async def publish(self, **kwargs) -> None:
            return None

    published_before = sample("wallet_outbox_published_total")
    await OutboxRelay(pool, SilentBroker()).publish_pending()

    await client.get("/metrics")
    assert sample("wallet_outbox_backlog") == 0  # drained
    assert sample("wallet_outbox_published_total") - published_before == 3


async def test_failed_publishes_are_counted_and_the_backlog_stays(client, pool):
    await pool.execute("DELETE FROM outbox_events")
    await outbox_repository.add_event(pool, "transfer.completed", {"n": 1})

    class DownBroker:
        async def publish(self, **kwargs) -> None:
            raise ConnectionError("broker down")

    failures_before = sample("wallet_outbox_publish_failures_total")

    with pytest.raises(ConnectionError, match="broker down"):
        await OutboxRelay(pool, DownBroker()).publish_pending()

    await client.get("/metrics")

    assert sample("wallet_outbox_publish_failures_total") - failures_before == 1
    assert sample("wallet_outbox_backlog") == 1
