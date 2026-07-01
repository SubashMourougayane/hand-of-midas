import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Hand of Midas — slate + emerald institutional palette.
        // Cool slate surfaces, emerald accent, semantic bull/bear tokens.
        // All fg/bg pairs ≥4.5:1 (skill: color-accessible-pairs).
        bg: {
          base: "#0a0e14",
          surface: "#11161f",
          elevated: "#161c25",
          card: "#1d2430",
          input: "#0d1218",
        },
        line: {
          subtle: "#1f2733",
          base: "#2c3645",
          strong: "#3a4554",
          accent: "#10b981",
        },
        ink: {
          primary: "#f1f3f6",
          secondary: "#c8cdd6",
          muted: "#8c95a4",
          dim: "#6a7384",
          inverse: "#0a0e14",
        },
        // Emerald accent system (replaces neon-green)
        brass: {
          DEFAULT: "#10b981",
          hi: "#34d399",
          dim: "#047857",
          tint: "rgba(16,185,129,0.10)",
        },
        bull: {
          DEFAULT: "#34d399",
          hi: "#6ee7b7",
          dim: "#047857",
          bg: "rgba(52,211,153,0.10)",
          glow: "rgba(52,211,153,0.25)",
        },
        bear: {
          DEFAULT: "#f87171",
          hi: "#fca5a5",
          dim: "#991b1b",
          bg: "rgba(248,113,113,0.10)",
          glow: "rgba(248,113,113,0.25)",
        },
        warn: {
          DEFAULT: "#fbbf24",
          dim: "#92400e",
          bg: "rgba(251,191,36,0.10)",
        },
        info: {
          DEFAULT: "#60a5fa",
          dim: "#1e3a8a",
          bg: "rgba(96,165,250,0.10)",
        },
        accent: {
          DEFAULT: "#10b981",
          hover: "#34d399",
          dim: "#047857",
        },
        // System mode accents
        live: "#34d399",
        bt: "#fbbf24",
      },
      fontFamily: {
        sans: [
          "IBM Plex Sans",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: [
          "IBM Plex Mono",
          "JetBrains Mono",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
        display: [
          "Fraunces",
          "Georgia",
          "serif",
        ],
      },
      fontSize: {
        "ds-xs": ["11px", { lineHeight: "16px" }],
        "ds-sm": ["13px", { lineHeight: "18px" }],
        "ds-base": ["14px", { lineHeight: "20px" }],
        "ds-md": ["15px", { lineHeight: "22px" }],
        "ds-lg": ["17px", { lineHeight: "26px" }],
        "ds-xl": ["20px", { lineHeight: "28px" }],
        "ds-2xl": ["26px", { lineHeight: "34px" }],
        "ds-3xl": ["32px", { lineHeight: "40px" }],
      },
      borderRadius: {
        ds: "6px",
        "ds-sm": "4px",
        "ds-lg": "10px",
      },
      boxShadow: {
        "ds-card": "inset 0 1px 0 rgba(255,255,255,0.02), 0 1px 2px rgba(0,0,0,0.3)",
        "ds-hover": "inset 0 1px 0 rgba(255,255,255,0.04), 0 4px 12px rgba(0,0,0,0.5)",
        "ds-glow-bull": "0 0 16px rgba(0,210,106,0.25)",
        "ds-glow-bear": "0 0 16px rgba(255,71,87,0.25)",
      },
      transitionDuration: {
        ds: "180ms",
      },
      animation: {
        "ds-pulse": "ds-pulse 1.5s ease-in-out infinite",
        "ds-flash-bull": "ds-flash-bull 600ms ease-out",
        "ds-flash-bear": "ds-flash-bear 600ms ease-out",
        "ds-shimmer": "ds-shimmer 1.6s ease-in-out infinite",
      },
      keyframes: {
        "ds-pulse": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        "ds-flash-bull": {
          "0%": { background: "rgba(0,210,106,0.25)" },
          "100%": { background: "transparent" },
        },
        "ds-flash-bear": {
          "0%": { background: "rgba(255,71,87,0.25)" },
          "100%": { background: "transparent" },
        },
        "ds-shimmer": {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
