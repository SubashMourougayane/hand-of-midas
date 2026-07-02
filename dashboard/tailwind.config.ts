import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Hand of Midas — BLACK / GREY GLASSMORPHISM.
        // Near-black base, frosted translucent grey panels (rgba + backdrop-blur),
        // luminous white hairline borders. One restrained accent (cool white/silver);
        // refined (non-neon) green/red for trade semantics. High contrast text.
        bg: {
          base: "#0a0b0d",      // near-black page
          surface: "#111316",   // opaque fallback surface
          elevated: "#181b1f",  // hovered/active
          card: "#141619",      // legacy
          input: "#0d0e11",     // inputs
        },
        // Glass fills — translucent greys meant to sit over the base with blur.
        glass: {
          DEFAULT: "rgba(255,255,255,0.05)",   // standard frosted panel
          strong: "rgba(255,255,255,0.08)",    // elevated / hovered glass
          subtle: "rgba(255,255,255,0.03)",    // faint inset
          border: "rgba(255,255,255,0.12)",    // luminous hairline
          "border-strong": "rgba(255,255,255,0.20)",
        },
        line: {
          subtle: "rgba(255,255,255,0.07)",   // hairline dividers
          base: "rgba(255,255,255,0.12)",     // borders
          strong: "rgba(255,255,255,0.20)",   // emphasized
          accent: "rgba(255,255,255,0.32)",   // bright edge
        },
        ink: {
          primary: "#f5f6f7",   // headlines
          secondary: "#c3c7cd", // body
          muted: "#8b9099",     // tertiary
          dim: "#5f646d",       // disabled/timestamps
          inverse: "#0a0b0d",   // dark-on-light
        },
        // Brand accent = cool silver-white (glass highlight).
        brass: {
          DEFAULT: "#e8eaed",
          hi: "#ffffff",
          dim: "#9aa0a8",
          tint: "rgba(255,255,255,0.08)",
        },
        // Bull (long) = refined glass green.
        bull: {
          DEFAULT: "#22c55e",
          hi: "#4ade80",
          dim: "#15803d",
          bg: "rgba(34,197,94,0.12)",
          glow: "rgba(34,197,94,0.28)",
        },
        // Bear (short) = refined glass red.
        bear: {
          DEFAULT: "#f04452",
          hi: "#ff6b76",
          dim: "#b3202c",
          bg: "rgba(240,68,82,0.12)",
          glow: "rgba(240,68,82,0.28)",
        },
        warn: {
          DEFAULT: "#e8a838",
          dim: "#7a5410",
          bg: "rgba(232,168,56,0.12)",
        },
        info: {
          DEFAULT: "#8ab4f8",
          dim: "#3b5578",
          bg: "rgba(138,180,248,0.12)",
        },
        accent: {
          DEFAULT: "#e8eaed",
          hover: "#ffffff",
          dim: "#9aa0a8",
        },
        // Legacy accent names — ALL collapse to the single silver/glass accent
        // so any leftover text-cyan / bg-lime / text-magenta renders monochrome
        // in the unified glass theme (no stray neon colors).
        cyan: {
          DEFAULT: "#c3c7cd",
          hi: "#f5f6f7",
          dim: "#8b9099",
          bg: "rgba(255,255,255,0.06)",
          glow: "rgba(255,255,255,0.18)",
        },
        lime: {
          DEFAULT: "#e8eaed",
          hi: "#ffffff",
          dim: "#9aa0a8",
          bg: "rgba(255,255,255,0.06)",
          glow: "rgba(255,255,255,0.18)",
        },
        magenta: {
          DEFAULT: "#c3c7cd",
          hi: "#f5f6f7",
          dim: "#8b9099",
          bg: "rgba(255,255,255,0.06)",
          glow: "rgba(255,255,255,0.18)",
        },
        // System mode accents
        live: "#22c55e",
        bt: "#e8a838",
      },
      fontFamily: {
        sans: [
          "Plus Jakarta Sans",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
        display: [
          "Space Grotesk",
          "Plus Jakarta Sans",
          "Inter",
          "sans-serif",
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
        ds: "12px",
        "ds-sm": "8px",
        "ds-lg": "18px",
        "ds-xl": "24px",
      },
      boxShadow: {
        // Glass depth: soft drop + top inner highlight (the frosted-edge sheen).
        "ds-card": "0 8px 32px -8px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.08)",
        "ds-hover": "0 16px 48px -12px rgba(0,0,0,0.7), inset 0 1px 0 rgba(255,255,255,0.12)",
        // Colored glow families keep their names (used across components) but are
        // now subtle white/semantic halos, not neon. cyan/lime/magenta = silver.
        "ds-glow-bull": "0 0 24px -6px rgba(34,197,94,0.4)",
        "ds-glow-bear": "0 0 24px -6px rgba(240,68,82,0.4)",
        "ds-glow-cyan": "0 0 24px -8px rgba(255,255,255,0.25)",
        "ds-glow-lime": "0 0 24px -8px rgba(255,255,255,0.25)",
        "ds-glow-magenta": "0 0 24px -8px rgba(255,255,255,0.25)",
        "ds-glow-cyan-lg": "0 0 48px -10px rgba(255,255,255,0.3), inset 0 1px 0 rgba(255,255,255,0.15)",
        "ds-glow-lime-lg": "0 0 48px -10px rgba(255,255,255,0.3), inset 0 1px 0 rgba(255,255,255,0.15)",
      },
      transitionDuration: {
        ds: "180ms",
      },
      animation: {
        "ds-pulse": "ds-pulse 1.5s ease-in-out infinite",
        "ds-flash-bull": "ds-flash-bull 600ms ease-out",
        "ds-flash-bear": "ds-flash-bear 600ms ease-out",
        "ds-shimmer": "ds-shimmer 1.6s ease-in-out infinite",
        "ds-neon-flicker": "ds-neon-flicker 3.5s linear infinite",
        "ds-glow-pulse": "ds-glow-pulse 2.4s ease-in-out infinite",
      },
      keyframes: {
        "ds-pulse": {
          "0%,100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        "ds-flash-bull": {
          "0%": { background: "rgba(34,197,94,0.3)" },
          "100%": { background: "transparent" },
        },
        "ds-flash-bear": {
          "0%": { background: "rgba(240,68,82,0.3)" },
          "100%": { background: "transparent" },
        },
        "ds-shimmer": {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        // Subtle neon-tube flicker for hero wordmarks.
        "ds-neon-flicker": {
          "0%,18%,22%,25%,53%,57%,100%": { opacity: "1" },
          "20%,24%,55%": { opacity: "0.55" },
        },
        // Breathing glow for live indicators / CTAs.
        "ds-glow-pulse": {
          "0%,100%": { filter: "brightness(1)", opacity: "0.92" },
          "50%": { filter: "brightness(1.25)", opacity: "1" },
        },
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
