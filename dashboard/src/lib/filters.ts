import { Trade } from "./api";
import { tradePnlUsd } from "./format";

export type FilterState = {
  status: Set<string>;       // "TP", "SL", "SL_BE", "TIMEOUT", "OPEN"
  side: Set<"LONG" | "SHORT">;
  leg: Set<string>;
  regime: Set<string>;
  outcome: Set<"WIN" | "LOSS" | "BE">;
  rBucket: Set<RBucket>;
  session: Set<Session>;
  year: Set<string>;
  holdBucket: Set<HoldBucket>;
  search: string;
  // Range filters (null = no bound)
  dateFrom: string | null;     // ISO date "YYYY-MM-DD"
  dateTo: string | null;
  rMin: number | null;
  rMax: number | null;
  pnlMin: number | null;       // $ pnl (uses raw_features.pnl_usd if present)
  pnlMax: number | null;
};

export type RBucket = "<-1R" | "-1..0" | "0..+1" | "+1..+2" | "+2..+4" | "+4R+";
export type Session = "asia" | "london" | "ny" | "off";
export type HoldBucket = "<1h" | "1-4h" | "4-24h" | "1d+";

export const EMPTY_FILTER: FilterState = {
  status: new Set(),
  side: new Set(),
  leg: new Set(),
  regime: new Set(),
  outcome: new Set(),
  rBucket: new Set(),
  session: new Set(),
  year: new Set(),
  holdBucket: new Set(),
  search: "",
  dateFrom: null,
  dateTo: null,
  rMin: null,
  rMax: null,
  pnlMin: null,
  pnlMax: null,
};

export function hasAnyFilter(f: FilterState): boolean {
  return (
    f.status.size > 0 ||
    f.side.size > 0 ||
    f.leg.size > 0 ||
    f.regime.size > 0 ||
    f.outcome.size > 0 ||
    f.rBucket.size > 0 ||
    f.session.size > 0 ||
    f.year.size > 0 ||
    f.holdBucket.size > 0 ||
    f.search.trim().length > 0 ||
    f.dateFrom != null ||
    f.dateTo != null ||
    f.rMin != null ||
    f.rMax != null ||
    f.pnlMin != null ||
    f.pnlMax != null
  );
}

export function rBucketOf(net_r: number | null | undefined): RBucket | null {
  if (net_r == null) return null;
  if (net_r < -1) return "<-1R";
  if (net_r < 0) return "-1..0";
  if (net_r < 1) return "0..+1";
  if (net_r < 2) return "+1..+2";
  if (net_r < 4) return "+2..+4";
  return "+4R+";
}

export function sessionOf(t: Trade): Session {
  // Use NY hour for session classification (matches strategy code).
  // Asia: NY 19-3 (which is UTC 0-8 next day mostly). London: NY 3-12, NY: 12-17.
  // Simple UTC-based heuristic since entry_timestamp is UTC.
  if (!t.entry_timestamp) return "off";
  const utcHr = new Date(t.entry_timestamp).getUTCHours();
  // London open ~07:00 UTC, NY open ~13:00 UTC, NY close ~21:00 UTC.
  if (utcHr >= 0 && utcHr < 7) return "asia";
  if (utcHr >= 7 && utcHr < 13) return "london";
  if (utcHr >= 13 && utcHr < 21) return "ny";
  return "off";
}

export function holdBucketOf(bars: number | null | undefined, tf: string = "M5"): HoldBucket {
  if (bars == null) return "<1h";
  // Bars per hour by timeframe
  const barsPerHr = tf === "M15" ? 4 : tf === "M5" ? 12 : tf === "M1" ? 60 : 4;
  const hrs = bars / barsPerHr;
  if (hrs < 1) return "<1h";
  if (hrs < 4) return "1-4h";
  if (hrs < 24) return "4-24h";
  return "1d+";
}

export function outcomeOf(net_r: number | null | undefined): "WIN" | "LOSS" | "BE" | null {
  if (net_r == null) return null;
  if (net_r > 0.05) return "WIN";
  if (net_r < -0.05) return "LOSS";
  return "BE";
}

export function statusOf(t: Trade): string {
  if (t.exit_timestamp == null) return "OPEN";
  return t.exit_reason ?? "CLOSED";
}

export function applyFilter(
  trades: Trade[],
  f: FilterState,
  tf: string = "M5",
  symbol?: string | null
): Trade[] {
  if (!hasAnyFilter(f)) return trades;
  const q = f.search.trim().toLowerCase();
  return trades.filter((t) => {
    if (f.status.size && !f.status.has(statusOf(t))) return false;
    if (f.side.size && !f.side.has(t.side > 0 ? "LONG" : "SHORT")) return false;
    if (f.leg.size && !(t.leg && f.leg.has(t.leg))) return false;
    if (f.regime.size && !(t.regime && f.regime.has(t.regime))) return false;
    if (f.outcome.size) {
      const o = outcomeOf(t.net_r);
      if (!o || !f.outcome.has(o)) return false;
    }
    if (f.rBucket.size) {
      const b = rBucketOf(t.net_r);
      if (!b || !f.rBucket.has(b)) return false;
    }
    if (f.session.size) {
      const s = sessionOf(t);
      if (!f.session.has(s)) return false;
    }
    if (f.year.size) {
      const y = (t.entry_timestamp ?? "").slice(0, 4);
      if (!f.year.has(y)) return false;
    }
    if (f.holdBucket.size) {
      const h = holdBucketOf(t.bars_held, tf);
      if (!f.holdBucket.has(h)) return false;
    }
    if (q) {
      const hay = `${t.trade_ref ?? ""} ${t.leg ?? ""} ${t.regime ?? ""} ${t.exit_reason ?? ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    // Date range
    if (f.dateFrom || f.dateTo) {
      const d = (t.entry_timestamp ?? "").slice(0, 10);
      if (f.dateFrom && d < f.dateFrom) return false;
      if (f.dateTo && d > f.dateTo) return false;
    }
    // R range
    if (f.rMin != null && (t.net_r ?? -Infinity) < f.rMin) return false;
    if (f.rMax != null && (t.net_r ?? Infinity) > f.rMax) return false;
    // $ PnL range — prefer raw_features.pnl_usd (sized) over 1.0-lot derive.
    if (f.pnlMin != null || f.pnlMax != null) {
      const pnl =
        (t.raw_features?.["pnl_usd"] as number | undefined) ??
        (t.net_r != null && t.risk_units != null && symbol
          ? t.net_r * t.risk_units * contractSize(symbol)
          : null);
      if (pnl == null) return false;
      if (f.pnlMin != null && pnl < f.pnlMin) return false;
      if (f.pnlMax != null && pnl > f.pnlMax) return false;
    }
    return true;
  });
}

const CS: Record<string, number> = {
  "XAUUSD.ecn": 100, "XAUUSD": 100,
  "EURUSD.ecn": 100_000, "EURUSD": 100_000,
  "GBPUSD.ecn": 100_000,
  "BRENT.ecn": 1000, "BRENT": 1000,
};
function contractSize(sym: string): number { return CS[sym] ?? 1; }

export function toCsv(trades: Trade[], symbol: string | null | undefined): string {
  const header = [
    "trade_ref",
    "side",
    "direction",
    "leg",
    "regime",
    "entry_ts",
    "entry_price",
    "stop_price",
    "tp_price",
    "exit_ts",
    "exit_price",
    "exit_reason",
    "risk_units",
    "bars_held",
    "gross_r",
    "cost_r",
    "net_r",
    "pnl_usd_1lot",
  ];
  const lines = trades.map((t) => {
    const pnl = tradePnlUsd(symbol, t.net_r, t.risk_units);
    return [
      t.trade_ref,
      t.side,
      t.direction,
      t.leg ?? "",
      t.regime ?? "",
      t.entry_timestamp ?? "",
      t.entry_price ?? "",
      t.stop_price ?? "",
      t.take_profit_price ?? "",
      t.exit_timestamp ?? "",
      t.exit_price ?? "",
      t.exit_reason ?? "",
      t.risk_units ?? "",
      t.bars_held ?? "",
      t.gross_r ?? "",
      t.cost_r ?? "",
      t.net_r ?? "",
      pnl ?? "",
    ]
      .map((v) =>
        typeof v === "string" && (v.includes(",") || v.includes('"'))
          ? `"${v.replace(/"/g, '""')}"`
          : String(v)
      )
      .join(",");
  });
  return [header.join(","), ...lines].join("\n");
}

export function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
