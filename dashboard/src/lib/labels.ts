// Single source of truth for human-facing labels.
// Kills raw engine jargon (intraday_a_long, fib_v2_intraday_d, GATE_SIGNAL_ZONE_MISS,
// "regime any", ...) so no _snake_case or SCREAMING_ENUM ever reaches the UI.

/** Strategy / leg → a clean product name + short tag + side. */
export type LegInfo = {
  name: string; // "Momentum Long"
  short: string; // "Long A"
  side: "long" | "short" | "both";
};

export function legInfo(strategyId?: string | null): LegInfo {
  const s = (strategyId ?? "").toLowerCase();
  if (s.includes("a_plus_d") || s.includes("aplusd"))
    return { name: "All positions", short: "All", side: "both" };
  if (s.endsWith("_a") || s.includes("_a_") || s.includes("intraday_a"))
    return { name: "Long", short: "Long", side: "long" };
  if (s.endsWith("_d") || s.includes("_d_") || s.includes("intraday_d"))
    return { name: "Short", short: "Short", side: "short" };
  if (s.includes("sdr")) return { name: "Supply / Demand", short: "S/D", side: "both" };
  return { name: prettify(s || "Strategy"), short: "—", side: "both" };
}

/** Side from a numeric side (+1/-1) → "Long" / "Short". */
export const sideLabel = (side?: number | null): string =>
  side == null ? "—" : side > 0 ? "Long" : "Short";

/** Human label for a strategy id (just the name). */
export const legName = (strategyId?: string | null): string => legInfo(strategyId).name;

/** Turn any snake/screaming token into Title Case words. */
export function prettify(raw?: string | null): string {
  if (!raw) return "—";
  return String(raw)
    .replace(/^(GATE|EXIT|ENTRY)_/i, "")
    .replace(/^fib_v2_/i, "")
    .replace(/^intraday_/i, "")
    .replace(/[_\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Regime → human phrase (hide the literal "any"). */
export function regimeLabel(regime?: string | null): string {
  const r = (regime ?? "").toLowerCase();
  if (!r || r === "any" || r === "none") return "All regimes";
  if (r === "trend") return "Trending";
  if (r === "range" || r === "chop") return "Ranging";
  return prettify(r);
}

/** Gate / journal event type → plain-English label. */
const GATE_LABELS: Record<string, string> = {
  GATE_PIVOT_DETECTED: "Pivot detected",
  GATE_SETUP_BUILT: "Setup built",
  GATE_SETUP_INVALIDATED: "Setup invalidated",
  GATE_SETUP_EXPIRED: "Setup expired",
  GATE_SIGNAL_STRICT_AFTER_FAIL: "Strict filter blocked",
  GATE_SIGNAL_ZONE_MISS: "Price missed zone",
  GATE_SIGNAL_SESSION_FAIL: "Outside session",
  GATE_SIGNAL_CONFIRM_FAIL: "No confirmation",
  GATE_SIGNAL_PASSED: "Signal passed",
  GATE_FINALIZE_RISK_INVALID: "Invalid risk",
  GATE_FINALIZE_RISK_PCT_CAP: "Risk cap hit",
  GATE_FINALIZE_MIN_RISK_FLOOR: "Below min risk",
  GATE_FINALIZE_DEDUP_COLLISION: "Duplicate setup",
  GATE_SETUP_REJECT_PIVOT_ORDER: "Bad pivot order",
  ENTRY_SUBMIT: "Order submitted",
  ENTRY_FILL: "Filled",
  EXIT_TP: "Take profit",
  EXIT_SL: "Stop loss",
  EXIT_SL_BE: "Breakeven stop",
  EXIT_TIMEOUT: "Time exit",
  PARTIAL_TP_APPLIED: "Partial booked",
  OPEN_STATE: "Position open",
  BAR: "Bar close",
};

export const gateLabel = (status?: string | null): string =>
  (status && GATE_LABELS[status]) || prettify(status);
