import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import * as api from "../api/client";
import type { User } from "../api/types";
import { describeError } from "../lib/errors";

// The JWT lives in sessionStorage: it survives a reload but not a closed tab. Trade-off: any script
// running on the page could read it (an XSS bug would expose it). The nginx CSP blocks inline and
// third-party scripts to reduce that risk; httpOnly cookies would remove it but need CSRF handling.
const TOKEN_KEY = "wallet.token";

function readToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: the user simply has to sign in again after a reload
  }
}

interface AuthValue {
  user: User | null;
  loading: boolean;
  notice: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const tokenRef = useRef<string | null>(readToken());
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(tokenRef.current !== null);
  const [notice, setNotice] = useState<string | null>(null);

  const clearSession = useCallback((message: string | null) => {
    tokenRef.current = null;
    writeToken(null);
    setUser(null);
    setNotice(message);
  }, []);

  useEffect(() => {
    api.configureApi({
      getToken: () => tokenRef.current,
      onUnauthorized: () => clearSession("Your session ended. Sign in again."),
    });
  }, [clearSession]);

  useEffect(() => {
    if (tokenRef.current === null) return;
    let cancelled = false;
    api
      .getMe()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        // a 401 already cleared the session with its own message
        if (!(error instanceof api.ApiError && error.status === 401)) clearSession(describeError(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const token = await api.login(email, password);
      tokenRef.current = token.access_token;
      writeToken(token.access_token);
      try {
        setUser(await api.getMe());
        setNotice(null);
      } catch (error) {
        clearSession(null);
        throw error;
      }
    },
    [clearSession],
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      await api.register(email, password);
      await signIn(email, password);
    },
    [signIn],
  );

  const signOut = useCallback(() => clearSession(null), [clearSession]);

  const value = useMemo(
    () => ({ user, loading, notice, signIn, signUp, signOut }),
    [user, loading, notice, signIn, signUp, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (value === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
