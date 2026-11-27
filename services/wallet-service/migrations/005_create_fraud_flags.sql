-- Fraud flags are advisory: the rule flags and logs, it never blocks a transfer.
CREATE TABLE fraud_flags (
    id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID        NOT NULL,
    rule                   TEXT        NOT NULL,
    transfer_count         INTEGER     NOT NULL,  -- how many transfers the user had made in the window
    window_seconds         INTEGER     NOT NULL,
    triggering_transfer_id UUID        NOT NULL REFERENCES transfers (id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fraud_flags_rule_valid     CHECK (rule IN ('transfer_velocity')),
    CONSTRAINT fraud_flags_count_positive CHECK (transfer_count > 0)
);

CREATE INDEX fraud_flags_user_created_idx ON fraud_flags (user_id, created_at DESC);
CREATE INDEX fraud_flags_created_idx ON fraud_flags (created_at DESC);

-- Serves the velocity rule ("how many transfers did this user make in the last minute?").
CREATE INDEX transfers_initiated_by_created_idx
    ON transfers (initiated_by, created_at DESC) WHERE type = 'transfer';
