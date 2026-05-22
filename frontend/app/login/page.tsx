"use client";

import { useState, FormEvent } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const { login, user } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // If already logged in, redirect
  if (user) {
    router.push("/live");
    return null;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const result = await login(email, password);
    if (!result.success) {
      setError(result.error || "Login failed");
    }
    setLoading(false);
  };

  return (
    <div style={{
      minHeight: "100vh",
      width: "100%",
      background: "#0a0d12",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      position: "relative",
      overflow: "hidden",
    }}>
      {/* Background grid */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", opacity: 0.3,
        backgroundImage: `linear-gradient(rgba(37, 42, 51, 0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(37, 42, 51, 0.3) 1px, transparent 1px)`,
        backgroundSize: "60px 60px",
      }} />

      {/* Gold ambient glow */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none",
        background: "radial-gradient(600px circle at 50% 40%, rgba(232, 195, 0, 0.04), transparent 60%)",
      }} />

      {/* Login card */}
      <div style={{
        position: "relative",
        zIndex: 1,
        width: "100%",
        maxWidth: 400,
        margin: "0 20px",
      }}>
        {/* Brand header */}
        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>&#x1F91A;</div>
          <h1 style={{
            fontSize: 24,
            fontWeight: 800,
            letterSpacing: "-0.02em",
            background: "linear-gradient(135deg, #e8c300, #ffdf4a)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            marginBottom: 8,
          }}>
            HAND OF MIDAS
          </h1>
          <p style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.15em" }}>
            Terminal Access
          </p>
        </div>

        {/* Form panel */}
        <div style={{
          background: "#111318",
          border: "1px solid #252a33",
          padding: "32px 28px",
        }}>
          {/* Top accent line */}
          <div style={{
            position: "absolute", top: 0, left: 28, right: 28, height: 1,
            background: "linear-gradient(90deg, transparent, #e8c300, transparent)",
          }} />

          <div style={{
            fontSize: 11,
            color: "#9ca3b4",
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            marginBottom: 24,
            paddingBottom: 16,
            borderBottom: "1px solid #1a1f28",
          }}>
            <span style={{ color: "#e8c300" }}>$</span> authenticate
          </div>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 20 }}>
              <label style={{
                display: "block", fontSize: 10, color: "#6b7280",
                textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8,
              }}>
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                style={{
                  width: "100%",
                  padding: "12px 14px",
                  background: "#0a0d12",
                  border: "1px solid #252a33",
                  color: "#c8cdd5",
                  fontSize: 13,
                  outline: "none",
                  transition: "border-color 0.2s",
                }}
                onFocus={(e) => e.currentTarget.style.borderColor = "#e8c300"}
                onBlur={(e) => e.currentTarget.style.borderColor = "#252a33"}
                placeholder="admin@midas.io"
              />
            </div>

            <div style={{ marginBottom: 28 }}>
              <label style={{
                display: "block", fontSize: 10, color: "#6b7280",
                textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8,
              }}>
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                style={{
                  width: "100%",
                  padding: "12px 14px",
                  background: "#0a0d12",
                  border: "1px solid #252a33",
                  color: "#c8cdd5",
                  fontSize: 13,
                  outline: "none",
                  transition: "border-color 0.2s",
                }}
                onFocus={(e) => e.currentTarget.style.borderColor = "#e8c300"}
                onBlur={(e) => e.currentTarget.style.borderColor = "#252a33"}
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div style={{
                marginBottom: 20,
                padding: "10px 14px",
                background: "#3d141420",
                border: "1px solid #5c1a1a",
                color: "#ff3e3e",
                fontSize: 12,
              }}>
                <span style={{ marginRight: 8 }}>&#x26A0;</span>{error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                width: "100%",
                padding: "14px",
                background: loading ? "#3d3200" : "linear-gradient(135deg, #e8c300, #c5a500)",
                color: "#000",
                border: "none",
                fontSize: 12,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                cursor: loading ? "wait" : "pointer",
                transition: "all 0.2s",
                opacity: loading ? 0.7 : 1,
              }}
            >
              {loading ? "Authenticating..." : "Access Terminal"}
            </button>
          </form>

          <div style={{
            marginTop: 20,
            paddingTop: 16,
            borderTop: "1px solid #1a1f28",
            textAlign: "center",
            fontSize: 10,
            color: "#4b5563",
          }}>
            Hand Of Midas v1.0 &mdash; Authorized personnel only
          </div>
        </div>

        {/* Back to home link */}
        <div style={{ textAlign: "center", marginTop: 20 }}>
          <a
            href="/"
            style={{
              fontSize: 11,
              color: "#6b7280",
              textDecoration: "none",
              transition: "color 0.2s",
            }}
            onMouseEnter={(e) => e.currentTarget.style.color = "#e8c300"}
            onMouseLeave={(e) => e.currentTarget.style.color = "#6b7280"}
          >
            &larr; Back to landing
          </a>
        </div>
      </div>
    </div>
  );
}
