CREATE TABLE wallets (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID,       -- id of the user in auth-service; no foreign key across databases
    kind       TEXT        NOT NULL DEFAULT 'user',
    currency   TEXT        NOT NULL DEFAULT 'INR',
    balance    BIGINT      NOT NULL DEFAULT 0,  -- integer paise, never floats
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT wallets_user_currency_key UNIQUE (user_id, currency),
    CONSTRAINT wallets_kind_valid        CHECK (kind IN ('user', 'system')),
    CONSTRAINT wallets_currency_valid    CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT wallets_owner_matches_kind CHECK (
        (kind = 'user'   AND user_id IS NOT NULL) OR
        (kind = 'system' AND user_id IS NULL)
    ),
    -- Backstop for "never negative": even a bug in the app cannot overdraw a user wallet.
    -- Only the system wallet (the counter-party of deposits) may go negative.
    CONSTRAINT wallets_balance_non_negative CHECK (kind = 'system' OR balance >= 0)
);

CREATE UNIQUE INDEX wallets_one_system_wallet_per_currency ON wallets (currency) WHERE kind = 'system';

-- The id must match SYSTEM_WALLET_ID in app/constants.py.
INSERT INTO wallets (id, kind) VALUES ('00000000-0000-0000-0000-000000000001', 'system');
