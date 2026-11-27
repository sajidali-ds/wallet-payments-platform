import json
from uuid import uuid4

import pytest

from app.consumers.transfer_consumer import PoisonMessage, parse_event
from app.schemas.event import EventEnvelope
from app.services.notification_service import build_notifications, format_money


def _event(**data_overrides) -> dict:
    data = {
        "transfer_id": str(uuid4()),
        "type": "transfer",
        "from_wallet_id": str(uuid4()),
        "from_user_id": str(uuid4()),
        "to_wallet_id": str(uuid4()),
        "to_user_id": str(uuid4()),
        "amount": 123_456,
        "currency": "INR",
    } | data_overrides
    return {
        "event_id": str(uuid4()),
        "event_type": "transfer.completed",
        "occurred_at": "2026-11-19T10:30:00+00:00",
        "data": data,
    }


@pytest.mark.parametrize(
    ("paise", "text"),
    [(0, "INR 0.00"), (5, "INR 0.05"), (100, "INR 1.00"), (123_456, "INR 1,234.56")],
)
def test_format_money_uses_integer_arithmetic(paise, text):
    assert format_money(paise, "INR") == text


def test_transfer_notifies_both_sides():
    event = EventEnvelope.model_validate(_event())
    notes = {n.type: n for n in build_notifications(event)}
    assert set(notes) == {"transfer.received", "transfer.sent"}
    assert notes["transfer.received"].user_id == event.data.to_user_id
    assert notes["transfer.received"].message == "You received INR 1,234.56"
    assert notes["transfer.sent"].user_id == event.data.from_user_id
    assert notes["transfer.sent"].message == "You sent INR 1,234.56"


def test_deposit_notifies_only_the_recipient():
    event = EventEnvelope.model_validate(_event(type="deposit", from_user_id=None, amount=500))
    notes = build_notifications(event)
    assert [(n.type, n.user_id) for n in notes] == [("deposit.received", event.data.to_user_id)]


def test_unknown_extra_fields_are_ignored_for_forward_compatibility():
    event = EventEnvelope.model_validate(_event(new_field_from_the_future="x"))
    assert event.data.amount == 123_456


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b'{"event_id": "x"}',
        json.dumps({**_event(), "event_type": "something.else"}).encode(),
        json.dumps(_event(amount=0)).encode(),
        json.dumps(_event(amount=1.5)).encode(),
    ],
)
def test_bad_messages_are_poison(body):
    with pytest.raises(PoisonMessage):
        parse_event(body)


def test_envelope_carries_the_request_id_and_it_is_optional():
    with_id = EventEnvelope.model_validate({**_event(), "request_id": "trace-1"})
    assert with_id.request_id == "trace-1"
    assert EventEnvelope.model_validate(_event()).request_id is None  # older producers


def test_valid_message_parses():
    assert parse_event(json.dumps(_event()).encode()).event_type == "transfer.completed"
