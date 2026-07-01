import { format as fnsFormat, parseISO } from "date-fns";

export const fmtPrice = (v?: number | null, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(digits);

// Auto-precision: 2 decimals for prices ≥1, but 5 decimals for sub-unit values
// (forex pips, fractional risk units). Picks the digit count that surfaces signal.
export const fmtPriceAuto = (v?: number | null) => {
  if (v == null || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 100) return v.toFixed(2);
  if (abs >= 1) return v.toFixed(3);
  if (abs >= 0.01) return v.toFixed(4);
  return v.toFixed(5);
};

// Symbol-aware price precision. Forex = 5 decimals, metals = 2, crypto = varies.
// Falls back to auto if symbol unknown.
const PRICE_DIGITS: Record<string, number> = {
  "XAUUSD.ecn": 2,
  "XAUUSD": 2,
  "BRENT.ecn": 2,
  "BRENT": 2,
  "EURUSD.ecn": 5,
  "EURUSD": 5,
  "GBPUSD.ecn": 5,
  "GBPUSD": 5,
  "USDJPY.ecn": 3,
  "USDJPY": 3,
  "AUDUSD.ecn": 5,
  "AUDUSD": 5,
};

export const fmtPriceFor = (symbol: string | null | undefined, v?: number | null) => {
  if (v == null || Number.isNaN(v)) return "—";
  const d = symbol && PRICE_DIGITS[symbol] != null ? PRICE_DIGITS[symbol] : null;
  if (d != null) return v.toFixed(d);
  return fmtPriceAuto(v);
};

// Contract size per symbol — used to convert R-multiples to real $ at qty=1 lot.
// Real $ PnL = net_r × risk_units × contract_size  (since BT uses qty=1.0 placeholder).
const CONTRACT_SIZE: Record<string, number> = {
  "XAUUSD.ecn": 100,
  "XAUUSD": 100,
  "BRENT.ecn": 1000,
  "BRENT": 1000,
  "EURUSD.ecn": 100_000,
  "EURUSD": 100_000,
  "GBPUSD.ecn": 100_000,
  "GBPUSD": 100_000,
  "USDJPY.ecn": 100_000,
  "USDJPY": 100_000,
  "AUDUSD.ecn": 100_000,
  "AUDUSD": 100_000,
};

export const contractSizeFor = (symbol: string | null | undefined): number => {
  if (!symbol) return 1;
  return CONTRACT_SIZE[symbol] ?? 1;
};

// "pip size" for a symbol — risk_units / pipSize = number of pips.
// Forex 1 pip = 0.0001 (JPY: 0.01). XAU: 0.01 ($0.01 = "1 pip"). BRENT: 0.01.
const PIP_SIZE: Record<string, number> = {
  "XAUUSD.ecn": 0.01,
  "XAUUSD": 0.01,
  "BRENT.ecn": 0.01,
  "BRENT": 0.01,
  "EURUSD.ecn": 0.0001,
  "EURUSD": 0.0001,
  "GBPUSD.ecn": 0.0001,
  "GBPUSD": 0.0001,
  "USDJPY.ecn": 0.01,
  "USDJPY": 0.01,
  "AUDUSD.ecn": 0.0001,
  "AUDUSD": 0.0001,
};

export const pipSizeFor = (symbol: string | null | undefined): number => {
  if (!symbol) return 1;
  return PIP_SIZE[symbol] ?? 1;
};

// Format risk_units as "pips" for forex / "$X.XX" for metals.
//   EUR/USD: 0.00070 → "7.0 pips"
//   XAU:     3.50    → "350 pips" (each $0.01 = 1 pip) — but more readable as "$3.50"
export const fmtRiskFor = (
  symbol: string | null | undefined,
  risk?: number | null
): string => {
  if (risk == null) return "—";
  const pip = pipSizeFor(symbol);
  const pips = risk / pip;
  // Metals: dollars are more intuitive than pip count.
  if (symbol?.startsWith("XAU") || symbol?.startsWith("BRENT")) {
    return `$${risk.toFixed(2)}`;
  }
  // Forex: show pips.
  return `${pips.toFixed(1)} pips`;
};

// Convert M-bars to human-readable duration.
// barsToDuration(238, "M5") → "19h 50m"
// barsToDuration(23, "M15") → "5h 45m"
const TF_MINUTES: Record<string, number> = {
  M1: 1, M3: 3, M5: 5, M15: 15, M30: 30,
  H1: 60, H4: 240, D1: 1440,
};

export const barsToDuration = (
  bars?: number | null,
  tf: string = "M5"
): string => {
  if (bars == null) return "—";
  const minPerBar = TF_MINUTES[tf] ?? 5;
  const totalMin = bars * minPerBar;
  if (totalMin < 60) return `${totalMin}m`;
  const days = Math.floor(totalMin / (24 * 60));
  const hrs = Math.floor((totalMin % (24 * 60)) / 60);
  const mins = totalMin % 60;
  if (days > 0) return `${days}d ${hrs}h`;
  if (mins === 0) return `${hrs}h`;
  return `${hrs}h ${mins}m`;
};

// $ PnL for a single trade at qty=1.0 lot (BT convention).
//   gross_r × risk_units × contract_size = price-distance moved × lot size
// risk_units is the price distance per 1R (e.g. 0.0082 EUR or 3.50 XAU).
export const tradePnlUsd = (
  symbol: string | null | undefined,
  net_r?: number | null,
  risk_units?: number | null
): number | null => {
  if (net_r == null || risk_units == null) return null;
  return net_r * risk_units * contractSizeFor(symbol);
};

// PRODUCTION-spec $ PnL — if the trade carries a pre-computed `pnl_usd`
// in raw_features (combined runs replayed with EquitySizer), use it.
// Falls back to 1.0-lot math for legacy/unsigned runs.
export const tradePnlReal = (
  symbol: string | null | undefined,
  net_r?: number | null,
  risk_units?: number | null,
  raw_features?: Record<string, unknown> | null
): number | null => {
  const sized = raw_features?.["pnl_usd"];
  if (typeof sized === "number") return sized;
  return tradePnlUsd(symbol, net_r, risk_units);
};

// Helper: get the per-trade lot from raw_features (combined replay) or null.
export const tradeQtyLots = (
  raw_features?: Record<string, unknown> | null
): number | null => {
  const q = raw_features?.["qty_lots"];
  return typeof q === "number" ? q : null;
};

export const fmtR = (v?: number | null, digits = 2) => {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  return v >= 0 ? `+${s}` : s;
};

export const fmtPct = (v?: number | null, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const fmtTs = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return fnsFormat(parseISO(iso), "yyyy-MM-dd HH:mm:ss");
  } catch {
    return iso;
  }
};

export const fmtTime = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return fnsFormat(parseISO(iso), "HH:mm:ss");
  } catch {
    return iso;
  }
};

export const colorForR = (v?: number | null): string => {
  if (v == null) return "text-ink-muted";
  if (v > 0) return "text-bull";
  if (v < 0) return "text-bear";
  return "text-ink-muted";
};

export const colorForGateStatus = (status: string): string => {
  if (status === "GATE_SIGNAL_PASSED") return "text-bull";
  if (status.startsWith("GATE_PIVOT") || status.startsWith("GATE_SETUP_BUILT"))
    return "text-info";
  if (status.startsWith("GATE_")) return "text-bear";
  if (status === "ENTRY_FILL" || status === "EXIT_TP" || status === "ENTRY_SUBMIT")
    return "text-bull";
  if (status === "EXIT_SL") return "text-bear";
  if (status === "EXIT_TIMEOUT") return "text-warn";
  return "text-ink-secondary";
};

export const bgForGateStatus = (status: string): string => {
  if (status === "GATE_SIGNAL_PASSED") return "#00D26A";
  if (status.startsWith("GATE_PIVOT") || status.startsWith("GATE_SETUP_BUILT"))
    return "#3DAEFF";
  if (status.startsWith("GATE_")) return "#FF4757";
  if (status === "ENTRY_FILL" || status === "EXIT_TP") return "#00D26A";
  if (status === "EXIT_SL") return "#FF4757";
  if (status === "EXIT_TIMEOUT") return "#FFA02E";
  return "#9BA4AE";
};

export const shortGateLabel = (status: string): string => {
  return status.replace(/^GATE_/, "").replace(/_/g, " ").toLowerCase();
};

export const fmtMoney = (v?: number | null, digits = 2) =>
  v == null || Number.isNaN(v)
    ? "—"
    : `$${v.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })}`;

export const fmtCompact = (v?: number | null) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1_000_000
    ? `${(v / 1_000_000).toFixed(2)}M`
    : Math.abs(v) >= 1_000
    ? `${(v / 1_000).toFixed(2)}K`
    : v.toFixed(2);
