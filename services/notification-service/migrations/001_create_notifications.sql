CREATE TABLE notifications (
    id         BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id    UUID        NOT NULL,  -- id of the user in auth-service
    event_id   UUID        NOT NULL,  -- the event that caused this notification
    type       TEXT        NOT NULL,
    message    TEXT        NOT NULL,
    payload    JSONB       NOT NULL,
    read_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Second line of defence against duplicates: one notification per user per event.
    CONSTRAINT notifications_event_user_key UNIQUE (event_id, user_id)
);

CREATE INDEX notifications_user_id_id_idx ON notifications (user_id, id DESC);

-- The consumer's dedupe table. A row here means "this event has been fully handled".
-- It is written in the SAME transaction as the notifications, so they appear together or not at all.
CREATE TABLE processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
