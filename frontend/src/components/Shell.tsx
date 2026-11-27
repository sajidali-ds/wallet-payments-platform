import { useEffect, useState } from "react";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useWallet } from "../hooks/useWallet";
import { AdminView } from "./AdminView";
import { BalanceCard } from "./BalanceCard";
import { History } from "./History";
import { NotificationsView } from "./NotificationsView";
import { Notice } from "./Notice";
import { TransferForm } from "./TransferForm";

type View = "wallet" | "notifications" | "admin";

function viewFromHash(isAdmin: boolean): View {
  const name = window.location.hash.replace(/^#/, "");
  if (name === "notifications") return "notifications";
  if (name === "admin" && isAdmin) return "admin";
  return "wallet";
}

export function Shell({ user }: { user: User }) {
  const { signOut } = useAuth();
  const isAdmin = user.role === "admin";
  const [view, setView] = useState<View>(() => viewFromHash(isAdmin));
  const wallet = useWallet();
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash(isAdmin));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [isAdmin]);

  function go(next: View) {
    window.location.hash = next === "wallet" ? "" : next;
    setView(next);
  }

  async function createWallet() {
    setCreating(true);
    setCreateError(null);
    setCreateError(await wallet.create());
    setCreating(false);
  }

  const state = wallet.state;
  const ownWalletId = state.status === "ready" ? state.wallet.id : null;

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">Wallet Platform</span>
          <nav aria-label="Main">
            <button type="button" aria-current={view === "wallet" ? "page" : undefined} onClick={() => go("wallet")}>
              Wallet
            </button>
            <button
              type="button"
              aria-current={view === "notifications" ? "page" : undefined}
              onClick={() => go("notifications")}
            >
              Notifications
            </button>
            {isAdmin && (
              <button type="button" aria-current={view === "admin" ? "page" : undefined} onClick={() => go("admin")}>
                Admin
              </button>
            )}
          </nav>
          <div className="account">
            <span className="account-email">{user.email}</span>
            {isAdmin && <span className="badge">Admin</span>}
            <button type="button" className="secondary small" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="page">
        {view === "wallet" && (
          <>
            {state.status === "loading" && <p role="status">Loading your wallet…</p>}
            {state.status === "error" && (
              <div className="narrow">
                <Notice kind="error">{state.message}</Notice>
                <button type="button" className="secondary" onClick={() => void wallet.refresh(true)}>
                  Try again
                </button>
              </div>
            )}
            {state.status === "none" && (
              <section className="panel narrow" aria-labelledby="open-heading">
                <h2 id="open-heading">Open your wallet</h2>
                <p>You do not have a wallet yet. Create one to send and receive money in rupees.</p>
                {createError && <Notice kind="error">{createError}</Notice>}
                <button type="button" className="primary" onClick={() => void createWallet()} disabled={creating}>
                  {creating ? "Creating wallet…" : "Create wallet"}
                </button>
              </section>
            )}
            {state.status === "ready" && (
              <div className="layout">
                <div className="column">
                  <BalanceCard
                    wallet={state.wallet}
                    balance={state.balance}
                    refreshing={wallet.refreshing}
                    onRefresh={() => void wallet.refresh(true)}
                  />
                  <TransferForm walletId={state.wallet.id} onTransferred={wallet.applyBalance} />
                </div>
                <History reloadKey={wallet.version} />
              </div>
            )}
          </>
        )}

        {view === "notifications" && <NotificationsView />}

        {view === "admin" && isAdmin && (
          <AdminView
            ownWalletId={ownWalletId}
            onDeposited={(walletId) => {
              if (walletId === ownWalletId) void wallet.refresh();
            }}
          />
        )}
      </main>
    </>
  );
}
