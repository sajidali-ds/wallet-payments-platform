import json
from datetime import UTC, datetime
from uuid import uuid4

from app.outbox.relay import build_body


def test_envelope_has_the_fields_consumers_rely_on():
    event_id = uuid4()
    created = datetime(2026, 11, 19, 10, 30, tzinfo=UTC)
    row = {
        "id": event_id,
        "event_type": "transfer.completed",
        "created_at": created,
        "request_id": "req-123",
        "payload": json.dumps({"amount": 500, "type": "transfer"}),
    }

    envelope = json.loads(build_body(row))

    assert envelope == {
        "event_id": str(event_id),
        "event_type": "transfer.completed",
        "request_id": "req-123",
        "occurred_at": created.isoformat(),
        "data": {"amount": 500, "type": "transfer"},
    }
