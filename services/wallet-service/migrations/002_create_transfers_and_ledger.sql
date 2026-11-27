CREATE TABLE transfers (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    type           TEXT        NOT NULL,
    from_wallet_id UUID        NOT NULL REFERENCES wallets (id),
    to_wallet_id   UUID        NOT NULL REFERENCES wallets (id),
    amount         BIGINT      NOT NULL,
    initiated_by   UUID        NOT NULL,  -- user who made the request (the admin, for deposits)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- No status column: a transfer is one atomic transaction, so a row exists only if it succeeded.
    CONSTRAINT transfers_type_valid        CHECK (type IN ('transfer', 'deposit')),
    CONSTRAINT transfers_amount_positive   CHECK (amount > 0),
    CONSTRAINT transfers_distinct_wallets  CHECK (from_wallet_id <> to_wallet_id)
);

-- Double-entry ledger: every transfer writes exactly two rows, one negative and one positive.
CREATE TABLE ledger_entries (
    id            BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transfer_id   UUID        NOT NULL REFERENCES transfers (id),
    wallet_id     UUID        NOT NULL REFERENCES wallets (id),
    amount        BIGINT      NOT NULL,  -- signed: negative = debit, positive = credit
    balance_after BIGINT      NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ledger_entries_amount_nonzero CHECK (amount <> 0),
    CONSTRAINT ledger_entries_one_per_wallet_per_transfer UNIQUE (transfer_id, wallet_id)
);

-- Serves "history of one wallet, newest first" and the keyset pagination on it.
CREATE INDEX ledger_entries_wallet_id_id_idx ON ledger_entries (wallet_id, id DESC);

-- Immutability: rows can be inserted, never changed or removed.
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$;

CREATE TRIGGER ledger_entries_append_only
    BEFORE UPDATE OR DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE TRIGGER transfers_append_only
    BEFORE UPDATE OR DELETE ON transfers
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Every transfer's entries must sum to zero. DEFERRABLE INITIALLY DEFERRED makes Postgres run the
-- check at COMMIT, when both entries exist (after the first insert alone the sum is not yet zero).
CREATE FUNCTION check_transfer_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT COALESCE(SUM(amount), 0) FROM ledger_entries WHERE transfer_id = NEW.transfer_id) <> 0 THEN
        RAISE EXCEPTION 'ledger entries of transfer % do not sum to zero', NEW.transfer_id;
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entries_balanced
    AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_transfer_balanced();
