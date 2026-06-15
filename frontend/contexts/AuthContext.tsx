"use client";

import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import { API_BASE } from "@/lib/client";

interface User {
  id: string;
  email: string;
  name?: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  login: async () => ({ success: false }),
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

const PUBLIC_PATHS = ["/", "/login", "/report", "/playbook"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  // Validate token on mount
  useEffect(() => {
    const token = localStorage.getItem("hom_token");
    if (!token) {
      setLoading(false);
      return;
    }

    fetch(`${API_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (res.ok) return res.json();
        throw new Error("Invalid token");
      })
      .then((data) => {
        setUser(data.user || data);
      })
      .catch(() => {
        localStorage.removeItem("hom_token");
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  // Redirect to login if not authenticated on protected routes
  useEffect(() => {
    if (loading) return;
    if (!user && !PUBLIC_PATHS.includes(pathname)) {
      router.replace("/login");
    }
  }, [user, loading, pathname, router]);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return { success: false, error: data.error || "Login failed" };
      }

      const data = await res.json();
      localStorage.setItem("hom_token", data.token);
      setUser(data.user);
      router.push("/live");
      return { success: true };
    } catch (err) {
      return { success: false, error: "Network error. Is the backend running?" };
    }
  }, [router]);

  const logout = useCallback(() => {
    localStorage.removeItem("hom_token");
    setUser(null);
    router.push("/login");
  }, [router]);

  // Don't render protected content until auth check completes.
  // Public pages render immediately; only protected routes block on auth.
  if (loading && !PUBLIC_PATHS.includes(pathname)) {
    return (
      <AuthContext.Provider value={{ user, loading, login, logout }}>
        <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
          <div className="flex items-center gap-2 text-[12px] text-[var(--color-text-muted)]">
            <span className="w-3 h-3 rounded-full border-2 border-[var(--color-brass)] border-t-transparent animate-spin" />
            <span>Authenticating</span>
          </div>
        </div>
      </AuthContext.Provider>
    );
  }

  // Block protected pages from rendering when not authenticated
  if (!user && !PUBLIC_PATHS.includes(pathname)) {
    return (
      <AuthContext.Provider value={{ user, loading, login, logout }}>
        <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
          <div className="text-[12px] text-[var(--color-text-muted)]">Redirecting…</div>
        </div>
      </AuthContext.Provider>
    );
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
