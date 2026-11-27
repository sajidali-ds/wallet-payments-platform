# Load test

What it measures, how to run it, and where the results go. **The results table at the bottom is empty on
purpose: numbers depend on your hardware, so they must come from a real run of `make loadtest`, never from a
document.** The command that fills it in (`make loadtest-report`) is below.

> **Never run this against production.** It creates dozens of funded accounts (INR 1,000,000 each), uses an
> admin login, raises the rate limits, and fills the ledger and the notification tables with test data.
> Use your laptop or a separate staging instance. The test users all share the password
> `load-test-password-1` (they only exist for the test), so delete the database afterwards (`make reset`).

## What is tested

`loadtests/k6/transfer.js` drives three flows at fixed arrival rates (k6 "open model": new iterations start on
schedule even if earlier ones are slow, so overload shows up honestly as latency or `dropped_iterations`).

| Flow | Default rate | What happens | Threshold (fails the run) |
|---|---|---|---|
| **Transfers** | 50/s | sender -> a different random user; body `{to_wallet_id, amount}`; **a fresh `Idempotency-Key` every time**; checks 201 and a transfer id | p95 < 500 ms |
| **Idempotent replays** | 5% of transfers | the same request sent again with the same key; must answer 201 with `Idempotent-Replay: true` and the same transfer id | 100% correct |
| **Balance reads** | 100/s | `GET /wallets/me/balance` for a random user (Redis cache + Postgres fallback) | p95 < 200 ms |
| **Logins** | 2/s | `POST /auth/login` (bcrypt, deliberately expensive) | p95 < 1500 ms |
| (all) | | | failed requests < 1%, checks > 99% |

`setup()` first registers `USERS` accounts (default 50), logs each in once, creates a wallet, and funds it
through the admin deposit endpoint (INR 1,000,000 each, so no transfer is ever rejected for lack of funds).
Each transfer is only 1-100 paise.

## How to run

```bash
make loadtest-up                                   # stack with relaxed per-user limits and quiet logs
make create-admin EMAIL=admin@example.com          # once; the password prompt is the ADMIN_PASSWORD below
ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD='...' make loadtest
make verify                                        # consistency checks (see below)
make loadtest-report                               # Markdown table: paste it into the results section
```

While it runs, open Grafana (`http://localhost:3000`, dashboard "Wallet Platform"): request rate, p95 latency,
the outbox backlog and the queue depth show where the system is straining.

Tuning (environment variables, all optional): `USERS` (50), `DURATION_SECONDS` (60), `TRANSFER_RATE` (50),
`READ_RATE` (100), `LOGIN_RATE` (2), `REPLAY_RATIO` (0.05). For example, hot senders (lock contention):
`USERS=2 TRANSFER_RATE=20 make loadtest`. Keep a run under 30 minutes: the JWTs created in setup expire then.
A rate of 0 turns that flow off.

### Honest limitations of the setup

- **k6 runs on the same machine as the system** by default, so they compete for CPU. For credible numbers run k6
  from a second instance (`AUTH_URL` / `WALLET_URL` pointing at the target) and record that in the table.
- The test talks to the **services directly**, not through the gateway: the gateway's `/auth` limit (30/min per IP)
  would throttle a load generator's logins, and nginx is not what is being measured.
- `docker-compose.loadtest.yml` raises the per-user rate limits (otherwise one user is capped at 20 transfers/min)
  and sets `LOG_LEVEL=WARNING` (an INFO line per request costs real throughput).
- Expect **fraud flags**: any user sending more than 5 transfers a minute is flagged (and logged), by design.
- Nothing is cleaned up between runs: `make reset` for a fresh database, then repeat.

## Why the numbers come out the way they do (what to look at)

| If you see | Likely cause | Where to look |
|---|---|---|
| transfer p95 grows with `USERS=2` | transfers of one sender serialise on its wallet row lock (by design: correctness) | Postgres lock waits; fewer, hotter senders is the worst case |
| `dropped_iterations` > 0 | the target rate exceeds what the single uvicorn process per service sustains | CPU of `wallet-service`; run more replicas or workers |
| login p95 far above everything else | bcrypt (cost 12, ~250 ms of CPU each) | lower `LOGIN_RATE`; this is the price of safe password storage |
| outbox backlog rising during the run, shrinking after | the relay (1 s poll, batches of 50) is slower than the transfer rate; no data is lost | Grafana "Outbox backlog"; raise the batch size or run more relays |
| queue depth rising | the consumer is slower than the producers | `notification_queue_depth`, consumer outcomes |
| 5xx | pool exhaustion (10 connections per service) or timeouts | service logs, `http_requests_total{status=~"5.."}` |

## Consistency check after the run (`make verify`)

`scripts/verify_consistency.sql` runs inside `wallet_db`; every row must show `violations = 0`:

| Check | What a failure would mean |
|---|---|
| `ledger_sums_to_zero` | the sum of **all** ledger entries is not 0: money was created or destroyed |
| `no_negative_user_balances` | a user wallet is overdrawn (only the system wallet may be negative) |
| `all_balances_sum_to_zero` | the wallet balances do not add up to 0 |
| `wallet_balance_equals_ledger_sum` | a `balance` column disagrees with its own ledger entries (a lost update) |
| `running_balance_consistent` | a ledger entry's `balance_after` is not the running sum of that wallet's entries |
| `transfer_entries_balanced` | a transfer does not have exactly two entries summing to 0 |
| `money_conserved` | the total in user wallets differs from the total ever deposited |
| `idempotency_keys_complete` | a key was stored without a response (a half-finished request) |
| `one_idempotency_key_per_user_transfer` | a transfer has no key, or the same key moved money twice |
| `every_transfer_has_one_outbox_event` | a committed transfer has no event, or several |

Then `scripts/verify_consistency.sh` checks the whole pipeline: the outbox is drained, **every event was
processed by notification-service exactly once** (`published == processed`), the notifications match the ledger
(2 per transfer + 1 per deposit), and no dead-letter queue holds a message. The checker itself is tested
(`tests/integration/test_consistency_sql.py`): it passes on healthy data and each corruption (a tampered balance,
an unbalanced ledger entry, a deleted event, ...) is caught by the check that is supposed to catch it.

## Results

> Not recorded yet. Run the test on the hardware you want to document, then paste the output of
> `make loadtest-report` here together with the output of `make verify`.

**Environment:** *(instance type / laptop model, where k6 ran, Docker version, date)*

*(output of `make loadtest-report`: throughput, latency percentiles, reliability)*

*(output of `make verify`: all checks PASS)*

**What I learned / what limited throughput:** *(a few sentences, with the Grafana panel that showed it)*
