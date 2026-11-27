import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import type { Wallet } from "../api/types";
import { describeError } from "../lib/errors";

export type WalletState =
  | { status: "loading" }
  | { status: "none" } // the user has not created a wallet yet
  | { status: "error"; message: string }
  | { status: "ready"; wallet: Wallet; balance: number };

const POLL_MS = 20_000;

export function useWallet() {
  const [state, setState] = useState<WalletState>({ status: "loading" });
  // Bumped whenever the balance changed, so the history list knows to reload itself.
  const [version, setVersion] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const lastBalance = useRef<number | null>(null);

  const refresh = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const [wallet, balance] = await Promise.all([api.getMyWallet(), api.getMyBalance()]);
      setState({ status: "ready", wallet, balance: balance.balance });
      if (lastBalance.current !== balance.balance) {
        lastBalance.current = balance.balance;
        setVersion((v) => v + 1);
      }
    } catch (error) {
      if (error instanceof api.ApiError && error.code === "wallet_not_found") {
        lastBalance.current = null;
        setState({ status: "none" });
      } else {
        // keep showing the last good numbers if a background refresh fails
        setState((previous) => (previous.status === "ready" ? previous : { status: "error", message: describeError(error) }));
      }
    } finally {
      if (showSpinner) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  const create = useCallback(async (): Promise<string | null> => {
    try {
      await api.createWallet();
    } catch (error) {
      if (!(error instanceof api.ApiError && error.code === "wallet_already_exists")) return describeError(error);
    }
    await refresh();
    return null;
  }, [refresh]);

  // The transfer response already carries the sender's new balance: show it without another request.
  const applyBalance = useCallback((balance: number) => {
    lastBalance.current = balance;
    setState((previous) => (previous.status === "ready" ? { ...previous, balance } : previous));
    setVersion((v) => v + 1);
  }, []);

  return { state, version, refreshing, refresh, create, applyBalance };
}
