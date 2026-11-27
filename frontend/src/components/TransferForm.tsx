import { useRef, useState } from "react";
import type { FormEvent } from "react";
import * as api from "../api/client";
import { isUuid, newIdempotencyKey, shortId } from "../lib/format";
import { describeError, isUncertain } from "../lib/errors";
import { formatPaise, parseRupees } from "../lib/money";
import { Notice } from "./Notice";

interface TransferFormProps {
  walletId: string;
  onTransferred: (balanceAfter: number) => void;
}

type Feedback =
  | { kind: "success"; text: string; transferId: string; replayed: boolean }
  | { kind: "error"; text: string }
  | { kind: "warning"; text: string };

interface FieldErrors {
  to?: string;
  amount?: string;
}

export function TransferForm({ walletId, onTransferred }: TransferFormProps) {
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [pending, setPending] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  // One Idempotency-Key per transfer attempt. If the answer gets lost (timeout, 5xx), pressing Send
  // again re-uses the SAME key, so the server replays the stored result instead of moving the money
  // a second time. The key is dropped once the outcome is known, so sending the same amount to the
  // same person again later is a new transfer.
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = to.trim();
    const errors: FieldErrors = {};
    if (!isUuid(target)) errors.to = "Enter the recipient’s wallet ID (it looks like 3f2a9c1e-…).";
    else if (target.toLowerCase() === walletId.toLowerCase()) errors.to = "That is your own wallet. Enter someone else’s ID.";
    const parsed = parseRupees(amount);
    if (!parsed.ok) errors.amount = parsed.reason;
    setFieldErrors(errors);
    if (errors.to || !parsed.ok) return;

    const fingerprint = `${target.toLowerCase()}|${parsed.paise}`;
    if (attempt.current === null || attempt.current.fingerprint !== fingerprint) {
      attempt.current = { fingerprint, key: newIdempotencyKey() };
    }

    setPending(true);
    setFeedback(null);
    try {
      const { transfer, replayed } = await api.createTransfer(target, parsed.paise, attempt.current.key);
      attempt.current = null;
      setAmount("");
      setFeedback({
        kind: "success",
        text: `Sent ${formatPaise(transfer.amount)} to ${shortId(transfer.to_wallet_id)}. Your new balance is ${formatPaise(transfer.balance_after)}.`,
        transferId: transfer.transfer_id,
        replayed,
      });
      onTransferred(transfer.balance_after);
    } catch (error) {
      if (isUncertain(error) || (error instanceof api.ApiError && error.code === "idempotency_key_in_progress")) {
        // keep the key: a retry is safe and cannot send the money twice
        setFeedback({
          kind: "warning",
          text: `${describeError(error)} We could not confirm this transfer. Press Send again to retry: it uses the same request key, so the money moves at most once.`,
        });
      } else {
        attempt.current = null;
        setFeedback({ kind: "error", text: describeError(error) });
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="transfer-heading">
      <h2 id="transfer-heading">Send money</h2>
      {feedback?.kind === "success" && (
        <Notice kind="success">
          <p>{feedback.text}</p>
          {feedback.replayed && <p>The server had already processed this request, so nothing was sent twice.</p>}
          <p className="fine">Transfer ID {feedback.transferId}</p>
        </Notice>
      )}
      {feedback?.kind === "warning" && <Notice kind="warning">{feedback.text}</Notice>}
      {feedback?.kind === "error" && <Notice kind="error">{feedback.text}</Notice>}

      <form onSubmit={onSubmit} noValidate>
        <div className="field">
          <label htmlFor="to-wallet">Recipient’s wallet ID</label>
          <input
            id="to-wallet"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={fieldErrors.to ? true : undefined}
            aria-describedby={fieldErrors.to ? "to-wallet-error" : undefined}
          />
          {fieldErrors.to && (
            <p id="to-wallet-error" className="field-error">
              {fieldErrors.to}
            </p>
          )}
        </div>
        <div className="field">
          <label htmlFor="amount">Amount in rupees</label>
          <div className="amount-input">
            <span aria-hidden="true">₹</span>
            <input
              id="amount"
              inputMode="decimal"
              autoComplete="off"
              placeholder="0.00"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-invalid={fieldErrors.amount ? true : undefined}
              aria-describedby={fieldErrors.amount ? "amount-error" : undefined}
            />
          </div>
          {fieldErrors.amount && (
            <p id="amount-error" className="field-error">
              {fieldErrors.amount}
            </p>
          )}
        </div>
        <button type="submit" className="primary" disabled={pending}>
          {pending ? "Sending…" : "Send"}
        </button>
      </form>
    </section>
  );
}
