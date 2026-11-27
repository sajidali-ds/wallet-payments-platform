import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import * as api from "../api/client";
import type { FraudFlag } from "../api/types";
import { describeError } from "../lib/errors";
import { formatDateTime, isUuid, shortId } from "../lib/format";
import { formatPaise, parseRupees } from "../lib/money";
import { Notice } from "./Notice";

interface AdminViewProps {
  ownWalletId: string | null;
  onDeposited: (walletId: string) => void;
}

type Feedback = { kind: "success" | "error" | "warning"; text: string } | null;

function DepositForm({ ownWalletId, onDeposited }: AdminViewProps) {
  const [walletId, setWalletId] = useState("");
  const [amount, setAmount] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [errors, setErrors] = useState<{ wallet?: string; amount?: string }>({});

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = walletId.trim();
    const nextErrors: { wallet?: string; amount?: string } = {};
    if (!isUuid(target)) nextErrors.wallet = "Enter the wallet ID to credit.";
    const parsed = parseRupees(amount);
    if (!parsed.ok) nextErrors.amount = parsed.reason;
    setErrors(nextErrors);
    if (nextErrors.wallet || !parsed.ok) return;

    setPending(true);
    setFeedback(null);
    try {
      const result = await api.depositToWallet(target, parsed.paise);
      setAmount("");
      setFeedback({
        kind: "success",
        text: `Credited ${formatPaise(result.amount)} to ${shortId(result.wallet_id)}. Its balance is now ${formatPaise(result.balance_after)}.`,
      });
      onDeposited(result.wallet_id);
    } catch (error) {
      const uncertain = error instanceof api.ApiError && (error.status === 0 || error.status >= 500);
      if (uncertain) {
        // Deposits have no Idempotency-Key (see the README limitations): a blind retry could credit twice.
        setFeedback({
          kind: "warning",
          text: `${describeError(error)} We cannot tell whether this deposit was applied. Check that wallet’s balance before trying again, because deposits are not idempotent and a retry could credit it twice.`,
        });
      } else {
        setFeedback({ kind: "error", text: describeError(error) });
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="deposit-heading">
      <h2 id="deposit-heading">Deposit funds</h2>
      <p className="hint">Credits a wallet from the system wallet. Intended for testing: only admins can do this.</p>
      {feedback && <Notice kind={feedback.kind}>{feedback.text}</Notice>}
      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="deposit-wallet">Wallet ID to credit</label>
          <input
            id="deposit-wallet"
            value={walletId}
            onChange={(e) => setWalletId(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={errors.wallet ? true : undefined}
            aria-describedby={errors.wallet ? "deposit-wallet-error" : undefined}
          />
          {ownWalletId && (
            <button type="button" className="link-button" onClick={() => setWalletId(ownWalletId)}>
              Use my wallet
            </button>
          )}
          {errors.wallet && (
            <p id="deposit-wallet-error" className="field-error">
              {errors.wallet}
            </p>
          )}
        </div>
        <div className="field">
          <label htmlFor="deposit-amount">Amount in rupees</label>
          <div className="amount-input">
            <span aria-hidden="true">₹</span>
            <input
              id="deposit-amount"
              inputMode="decimal"
              autoComplete="off"
              placeholder="0.00"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-invalid={errors.amount ? true : undefined}
              aria-describedby={errors.amount ? "deposit-amount-error" : undefined}
            />
          </div>
          {errors.amount && (
            <p id="deposit-amount-error" className="field-error">
              {errors.amount}
            </p>
          )}
        </div>
        <button type="submit" className="primary" disabled={pending}>
          {pending ? "Depositing…" : "Deposit"}
        </button>
      </form>
    </section>
  );
}

function FraudFlags() {
  const [flags, setFlags] = useState<FraudFlag[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setFlags(await api.listFraudFlags());
      setError(null);
    } catch (e) {
      setError(describeError(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="panel" aria-labelledby="fraud-heading">
      <div className="panel-head">
        <h2 id="fraud-heading">Flagged activity</h2>
        <button type="button" className="link-button" onClick={() => void load()}>
          Reload
        </button>
      </div>
      <p className="hint">Users are flagged, never blocked, when they make too many transfers in a short window.</p>
      {error && <Notice kind="error">{error}</Notice>}
      {flags === null && !error && <p role="status">Loading flags…</p>}
      {flags !== null && flags.length === 0 && <p className="empty-text">No flagged activity.</p>}
      {flags !== null && flags.length > 0 && (
        <ul className="entries">
          {flags.map((flag) => (
            <li key={flag.id}>
              <span className="entry-title">
                {flag.transfer_count} transfers in {flag.window_seconds} s
              </span>
              <span className="entry-amount">{flag.rule}</span>
              <span className="entry-meta">User {shortId(flag.user_id)}</span>
              <span className="entry-meta">{formatDateTime(flag.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AdminView(props: AdminViewProps) {
  return (
    <div className="layout">
      <DepositForm {...props} />
      <FraudFlags />
    </div>
  );
}
