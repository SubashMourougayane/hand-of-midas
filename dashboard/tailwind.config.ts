import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Bloomberg-grade palette
        term: {
          bg: "#000000",
          panel: "#0a0a0a",
          border: "#FF9933",
          amber: "#FF9933",
          amberDim: "#aa6620",
          green: "#00CC00",
          greenDim: "#007700",
          red: "#FF3333",
          redDim: "#aa2222",
          cyan: "#00CCFF",
          gray: "#666666",
          textPrimary: "#FFB347",
          textSecondary: "#cccccc",
          textMuted: "#777777",
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "IBM Plex Mono",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        "term-xs": "10px",
        "term-sm": "11px",
        "term-base": "12px",
        "term-lg": "14px",
      },
    },
  },
  plugins: [],
} satisfies Config;
