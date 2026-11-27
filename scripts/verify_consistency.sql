-- Data-consistency checks for wallet_db. ONE statement; every row is (check_name, violations, detail).
-- violations = 0 means the check passed. Rows named info_* are informational and always 0.
-- Run it with:  make verify   (scripts/verify_consistency.sh)   or   psql -d wallet_db -f this-file
SELECT 'ledger_sums_to_zero' AS check_name,
       (SELECT CASE WHEN COALESCE(SUM(amount), 0) = 0 THEN 0 ELSE 1 END FROM ledger_entries)::bigint AS violations,
       'sum of all ledger entries = ' || (SELECT COALESCE(SUM(amount), 0) FROM ledger_entries)::text AS detail

UNION ALL
SELECT 'no_negative_user_balances',
       (SELECT count(*) FROM wallets WHERE kind = 'user' AND balance < 0),
       'user wallets with a negative balance (only the system wallet may be negative)'

UNION ALL
SELECT 'all_balances_sum_to_zero',
       (SELECT CASE WHEN COALESCE(SUM(balance), 0) = 0 THEN 0 ELSE 1 END FROM wallets),
       'money is neither created nor destroyed: the sum of every wallet balance'

UNION ALL
SELECT 'wallet_balance_equals_ledger_sum',
       (SELECT count(*) FROM (
            SELECT w.id
            FROM wallets w
            LEFT JOIN ledger_entries le ON le.wallet_id = w.id
            GROUP BY w.id, w.balance
            HAVING w.balance <> COALESCE(SUM(le.amount), 0)) bad),
       'wallets whose balance column differs from the sum of their ledger entries'

UNION ALL
SELECT 'running_balance_consistent',
       (SELECT count(*) FROM (
            SELECT balance_after,
                   SUM(amount) OVER (PARTITION BY wallet_id ORDER BY id) AS running
            FROM ledger_entries) e
        WHERE e.balance_after <> e.running),
       'ledger entries whose balance_after differs from the running sum of that wallet''s entries'

UNION ALL
SELECT 'transfer_entries_balanced',
       (SELECT count(*) FROM (
            SELECT t.id
            FROM transfers t
            LEFT JOIN ledger_entries le ON le.transfer_id = t.id
            GROUP BY t.id
            HAVING COALESCE(SUM(le.amount), 0) <> 0 OR count(le.id) <> 2) bad),
       'transfers whose entries do not sum to zero or are not exactly two'

UNION ALL
SELECT 'money_conserved',
       (SELECT CASE
                 WHEN (SELECT COALESCE(SUM(balance), 0) FROM wallets WHERE kind = 'user')
                    = (SELECT COALESCE(SUM(amount), 0) FROM transfers WHERE type = 'deposit')
                 THEN 0 ELSE 1 END),
       'total in user wallets equals everything ever deposited'

UNION ALL
SELECT 'idempotency_keys_complete',
       (SELECT count(*) FROM idempotency_keys WHERE response_status IS NULL OR transfer_id IS NULL),
       'idempotency keys without a stored response (a half-finished request)'

UNION ALL
SELECT 'one_idempotency_key_per_user_transfer',
       (SELECT count(*) FROM (
            SELECT t.id
            FROM transfers t
            LEFT JOIN idempotency_keys k ON k.transfer_id = t.id
            WHERE t.type = 'transfer'
            GROUP BY t.id
            HAVING count(k.key) <> 1) bad),
       'user transfers that do not have exactly one idempotency key (money moved twice or unrecorded)'

UNION ALL
SELECT 'every_transfer_has_one_outbox_event',
       (SELECT count(*) FROM (
            SELECT t.id
            FROM transfers t
            LEFT JOIN outbox_events o ON (o.payload->>'transfer_id') = t.id::text
            GROUP BY t.id
            HAVING count(o.id) <> 1) bad),
       'transfers with zero or several transfer.completed events'

UNION ALL
SELECT 'info_counts',
       0,
       (SELECT count(*) FROM wallets WHERE kind = 'user')::text || ' user wallets, '
       || (SELECT count(*) FROM transfers WHERE type = 'transfer')::text || ' transfers, '
       || (SELECT count(*) FROM transfers WHERE type = 'deposit')::text || ' deposits, '
       || (SELECT count(*) FROM ledger_entries)::text || ' ledger entries'

UNION ALL
SELECT 'info_outbox_unpublished',
       0,
       (SELECT count(*) FROM outbox_events WHERE published_at IS NULL)::text
       || ' events still waiting for RabbitMQ (a backlog, not an inconsistency)'
