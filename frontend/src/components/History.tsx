import * as api from "../api/client";
import type { Transaction } from "../api/types";
import { usePaged } from "../hooks/usePaged";
import { formatDateTime, shortId } from "../lib/format";
import { formatPaise } from "../lib/money";
import { Notice } from "./Notice";

const fetchTransactions = (cursor: number | null) => api.listTransactions(20, cursor);

function describeEntry(entry: Transaction): string {
  if (entry.type === "deposit") return "Deposit";
  const who = shortId(entry.counterparty_wallet_id);
  return entry.amount < 0 ? `Sent to ${who}` : `Received from ${who}`;
}

export function History({ reloadKey }: { reloadKey: number }) {
  const { items, loading, loadingMore, error, hasMore, loadMore, reload } = usePaged(fetchTransactions, reloadKey);

  return (
    <section className="panel" aria-labelledby="history-heading">
      <div className="panel-head">
        <h2 id="history-heading">History</h2>
        <button type="button" className="link-button" onClick={reload} disabled={loading}>
          Reload
        </button>
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {loading && items.length === 0 && <p role="status">Loading history…</p>}
      {!loading && !error && items.length === 0 && (
        <p className="empty-text">No transactions yet. Money you send or receive will appear here.</p>
      )}

      {items.length > 0 && (
        <ul className="entries">
          {items.map((entry) => (
            <li key={entry.entry_id}>
              <span className="entry-title">{describeEntry(entry)}</span>
              <span className={`entry-amount ${entry.amount < 0 ? "debit" : "credit"}`}>
                {formatPaise(entry.amount, { showSign: true })}
              </span>
              <span className="entry-meta">{formatDateTime(entry.created_at)}</span>
              <span className="entry-meta">Balance {formatPaise(entry.balance_after)}</span>
            </li>
          ))}
        </ul>
      )}

      {hasMore && (
        <button type="button" className="secondary" onClick={() => void loadMore()} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Show older transactions"}
        </button>
      )}
    </section>
  );
}
