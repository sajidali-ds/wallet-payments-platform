import type { Wallet } from "../api/types";
import { formatPaise } from "../lib/money";
import { CopyButton } from "./CopyButton";

interface BalanceCardProps {
  wallet: Wallet;
  balance: number;
  refreshing: boolean;
  onRefresh: () => void;
}

export function BalanceCard({ wallet, balance, refreshing, onRefresh }: BalanceCardProps) {
  return (
    <section className="panel balance-panel" aria-labelledby="balance-heading">
      <div className="panel-head">
        <h2 id="balance-heading">Balance</h2>
        <button type="button" className="link-button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="balance-figure" aria-live="polite">
        {formatPaise(balance)}
      </p>
      <div className="wallet-id">
        <span id="wallet-id-label">Your wallet ID</span>
        <code aria-labelledby="wallet-id-label">{wallet.id}</code>
        <CopyButton text={wallet.id} label="Copy ID" />
      </div>
      <p className="hint">Share this ID with anyone who wants to send you money.</p>
    </section>
  );
}
