import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

const TOKEN_KEY = "hom.auth.token";

type AuthState = {
  token: string | null;
  ready: boolean; // finished the initial verify round-trip
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [ready, setReady] = useState(false);

  // Re-verify any stored token on load — expired/forged tokens get cleared so
  // ProtectedRoute bounces to /login instead of rendering a broken shell.
  useEffect(() => {
    let alive = true;
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t) {
      setReady(true);
      return;
    }
    api
      .verify(t)
      .then((ok) => {
        if (!alive) return;
        if (!ok) {
          localStorage.removeItem(TOKEN_KEY);
          setToken(null);
        }
      })
      .finally(() => alive && setReady(true));
    return () => {
      alive = false;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    localStorage.setItem(TOKEN_KEY, res.token);
    setToken(res.token);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }, []);

  return (
    <AuthCtx.Provider value={{ token, ready, login, logout }}>{children}</AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
