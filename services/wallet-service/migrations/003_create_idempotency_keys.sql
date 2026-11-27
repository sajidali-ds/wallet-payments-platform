-- Used by POST /transfers. The (user_id, key) primary key is what guarantees that two
-- requests with the same key from the same user can never both be inserted.
CREATE TABLE idempotency_keys (
    user_id         UUID        NOT NULL,
    key             TEXT        NOT NULL,
    request_hash    TEXT        NOT NULL,  -- hash of the request body: detects "same key, different payload"
    response_status INTEGER,               -- filled in when the request finishes
    response_body   JSONB,
    transfer_id     UUID        REFERENCES transfers (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT idempotency_keys_pkey       PRIMARY KEY (user_id, key),
    CONSTRAINT idempotency_keys_key_length CHECK (char_length(key) BETWEEN 1 AND 255)
);
