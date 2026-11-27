-- Transactional outbox: a transfer and its event are written in the SAME transaction, so either
-- both exist or neither does. A separate relay later copies unpublished rows to RabbitMQ.
CREATE TABLE outbox_events (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),  -- also the event id consumers dedupe on
    event_type   TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,  -- NULL = not yet sent to RabbitMQ

    CONSTRAINT outbox_events_type_nonempty CHECK (char_length(event_type) > 0)
);

-- Partial index: only the (small) backlog of unsent rows is indexed, so the relay's query and the
-- "outbox backlog" metric stay fast no matter how many sent rows pile up.
CREATE INDEX outbox_events_unpublished_idx ON outbox_events (created_at, id) WHERE published_at IS NULL;
