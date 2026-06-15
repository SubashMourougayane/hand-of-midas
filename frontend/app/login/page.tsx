"use client";

import { useState, FormEvent } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Card, Button, Display } from "@/components/ui";

export default function LoginPage() {
  const { login, user } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (user) {
    router.push("/live");
    return null;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const result = await login(email, password);
    if (!result.success) setError(result.error || "Login failed");
    setLoading(false);
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center relative overflow-hidden bg-[var(--color-bg)] p-5">
      {/* Background grid */}
      <div
        className="fixed inset-0 pointer-events-none opacity-30"
        aria-hidden
        style={{
          backgroundImage: `linear-gradient(var(--color-border) 1px, transparent 1px), linear-gradient(90deg, var(--color-border) 1px, transparent 1px)`,
          backgroundSize: "60px 60px",
        }}
      />
      {/* Brass ambient glow */}
      <div
        className="fixed inset-0 pointer-events-none"
        aria-hidden
        style={{
          background: "radial-gradient(600px circle at 50% 40%, rgba(212, 164, 100, 0.06), transparent 60%)",
        }}
      />

      <div className="relative z-10 w-full max-w-[400px] hom-fade-in-up">
        {/* Brand header */}
        <div className="text-center mb-9">
          <span
            className="inline-block w-3 h-3 rotate-45 bg-[var(--color-brass)] mb-4"
            aria-hidden
            style={{ boxShadow: "0 0 18px rgba(212,164,100,0.5)" }}
          />
          <Display size="lg" italic className="text-[var(--color-brass-hi)]">
            Hand of Midas
          </Display>
          <p className="text-[10px] uppercase tracking-[0.4em] text-[var(--color-text-muted)] mt-3">
            Terminal Access
          </p>
        </div>

        <Card className="relative overflow-hidden">
          {/* Top brass rule */}
          <div
            className="absolute top-0 left-0 right-0 h-px"
            style={{
              background: "linear-gradient(90deg, transparent, var(--color-brass), transparent)",
            }}
            aria-hidden
          />
          <div className="p-7">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-[var(--color-text-muted)] mb-5 pb-4 border-b border-[var(--color-border)]">
              <span className="text-[var(--color-brass-hi)] num">$</span>
              <span>authenticate</span>
            </div>

            <form onSubmit={handleSubmit} className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <label className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-text-muted)] font-medium">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  placeholder="admin@midas.io"
                  className="w-full"
                  style={{
                    padding: "12px 14px",
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text)",
                    fontSize: 13,
                    borderRadius: "var(--radius-md)",
                  }}
                />
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-[10px] uppercase tracking-[0.1em] text-[var(--color-text-muted)] font-medium">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="w-full"
                  style={{
                    padding: "12px 14px",
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text)",
                    fontSize: 13,
                    borderRadius: "var(--radius-md)",
                  }}
                />
              </div>

              {error ? (
                <div className="px-3 py-2.5 text-[12px] text-[var(--color-loss)] bg-[var(--color-loss)]/8 border border-[var(--color-loss)]/40 rounded-[5px]">
                  {error}
                </div>
              ) : null}

              <Button type="submit" variant="primary" size="lg" loading={loading} disabled={loading} className="w-full mt-1">
                {loading ? "Authenticating…" : "Access Terminal"}
              </Button>
            </form>

            <div className="mt-5 pt-4 border-t border-[var(--color-border)] text-center text-[10px] text-[var(--color-text-muted)]">
              Hand Of Midas v1.0 — Authorized personnel only
            </div>
          </div>
        </Card>

        <div className="text-center mt-6">
          <Link
            href="/"
            className="text-[11px] text-[var(--color-text-muted)] hover:text-[var(--color-brass-hi)] transition-colors"
          >
            ← Back to landing
          </Link>
        </div>
      </div>
    </div>
  );
}
