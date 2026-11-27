import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { describeError } from "../lib/errors";
import { Notice } from "./Notice";

type Mode = "signin" | "signup";

export function AuthPage() {
  const { signIn, signUp, notice } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const signingUp = mode === "signup";

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (signingUp && password.length < 8) {
      setError("Use a password with at least 8 characters.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      if (signingUp) await signUp(email.trim(), password);
      else await signIn(email.trim(), password);
    } catch (e) {
      setError(describeError(e));
      setPending(false);
    }
    // On success this page is replaced by the app, so there is nothing to reset.
  }

  return (
    <main className="auth">
      <section className="auth-intro" aria-labelledby="intro-heading">
        <h1 id="intro-heading">Wallet Platform</h1>
        <p className="auth-lead">Send money between wallets. A transfer is never duplicated and never lost, even when the network fails and you retry.</p>
        <dl className="mini-ledger" aria-label="Example of a double-entry transfer">
          <div>
            <dt>Asha’s wallet</dt>
            <dd className="debit">−₹1,200.00</dd>
          </div>
          <div>
            <dt>Ravi’s wallet</dt>
            <dd className="credit">+₹1,200.00</dd>
          </div>
          <div className="mini-ledger-total">
            <dt>Net change</dt>
            <dd>₹0.00</dd>
          </div>
        </dl>
        <p className="hint">Every transfer is written as two ledger entries that always add up to zero.</p>
      </section>

      <section className="auth-form panel" aria-labelledby="auth-heading">
        <div className="segmented" role="group" aria-label="Choose how to continue">
          <button type="button" aria-pressed={!signingUp} onClick={() => switchMode("signin")}>
            Sign in
          </button>
          <button type="button" aria-pressed={signingUp} onClick={() => switchMode("signup")}>
            Create account
          </button>
        </div>
        <h2 id="auth-heading">{signingUp ? "Create your account" : "Sign in to your wallet"}</h2>

        {notice && <Notice kind="warning">{notice}</Notice>}
        {error && <Notice kind="error">{error}</Notice>}

        <form onSubmit={onSubmit} noValidate>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={signingUp ? "new-password" : "current-password"}
              required
              minLength={signingUp ? 8 : undefined}
              maxLength={72}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={signingUp ? "password-hint" : undefined}
            />
            {signingUp && (
              <p id="password-hint" className="hint">
                At least 8 characters.
              </p>
            )}
          </div>
          <button type="submit" className="primary" disabled={pending || email.trim() === "" || password === ""}>
            {pending ? (signingUp ? "Creating account…" : "Signing in…") : signingUp ? "Create account" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
