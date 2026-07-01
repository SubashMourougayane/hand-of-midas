// Decodes a gate-decision signal into an animated checklist.
// Rich detail layout: two-column key/value grid for facts + inline chip callouts.

import { useEffect, useState } from "react";
import { Check, X as XIcon, Pause, Info } from "lucide-react";
import { fmtPriceAuto } from "../lib/format";

type Detail = Record<string, unknown> | null;

type CheckItem = {
  label: string;
  status: "pass" | "fail" | "skipped" | "info";
  value?: string;
  detail?: { k: string; v: string }[];  // optional key/value grid
};

function get<T = any>(d: Detail, k: string): T | undefined {
  if (!d) return undefined;
  return d[k] as T;
}

function fmt(v: any, digits = 2): string {
  if (v == null) return "—";
  if (typeof v === "number") return fmtPriceAuto(v) ?? v.toFixed(digits);
  return String(v);
}

function fmtTs(ts: any): string {
  if (!ts) return "—";
  const s = String(ts);
  // "2026-06-30 23:45:00+00:00" → "23:45"
  const m = s.match(/(\d{2}:\d{2})/);
  return m ? m[1] : s.slice(11, 16);
}

export function checklistFor(eventType: string, detail: Detail): CheckItem[] {
  const items: CheckItem[] = [];
  const side = get<number>(detail, "side");
  const L = get<number>(detail, "fib_L");
  const H = get<number>(detail, "fib_H");
  const diff = get<number>(detail, "fib_diff");
  const f382 = get<number>(detail, "fib_382");
  const f786 = get<number>(detail, "fib_786");
  const f100 = get<number>(detail, "fib_100");
  const sl = get<number>(detail, "sl_price");
  const tp = get<number>(detail, "tp_price");
  const close = get<number>(detail, "bar_close");
  const sessionGate = get<string>(detail, "session");
  const nyHr = get<number>(detail, "ny_hr");
  const regime = get<string>(detail, "regime");
  const reason = get<string>(detail, "reason");
  const pattern = get<string>(detail, "pattern");
  const risk = get<number>(detail, "risk");
  const riskUnits = get<number>(detail, "risk_units");
  const minRisk = get<number>(detail, "min_risk_units");
  const entryPrice = get<number>(detail, "entry_price");
  const direction = side === 1 ? "LONG" : side === -1 ? "SHORT" : null;

  const pivotItem: CheckItem = {
    label: "Pivot pair found",
    status: L != null && H != null ? "pass" : "skipped",
    detail:
      L != null && H != null
        ? [
            { k: "LOW", v: `$${fmt(L)}` },
            { k: "HIGH", v: `$${fmt(H)}` },
            { k: "Range", v: `$${fmt(diff)}` },
          ]
        : undefined,
  };
  const setupItem: CheckItem = {
    label: "Setup built (fib zone + stop + target)",
    status: f382 != null ? "pass" : "skipped",
    detail:
      f382 != null
        ? [
            { k: "Fib 100%", v: `$${fmt(f100)}` },
            { k: "Fib 78.6%", v: `$${fmt(f786)}` },
            { k: "Fib 38.2%", v: `$${fmt(f382)}` },
          ]
        : undefined,
  };
  const slTpItem: CheckItem = {
    label: "SL / TP levels",
    status: sl != null ? "pass" : "skipped",
    detail: sl != null ? [
      { k: "Stop", v: `$${fmt(sl)}` },
      { k: "Target", v: `$${fmt(tp)}` },
    ] : undefined,
  };

  if (eventType === "GATE_PIVOT_DETECTED") {
    const ptype = get<string>(detail, "pivot_type");
    const ppx = get<number>(detail, "pivot_price");
    items.push({
      label: `${ptype === "H" ? "New HIGH pivot" : "New LOW pivot"} confirmed`,
      status: "pass",
      detail: [
        { k: "Price", v: `$${fmt(ppx)}` },
        { k: "Confirm rule", v: "3 bars either side" },
      ],
    });
    return items;
  }

  if (eventType === "GATE_SETUP_BUILT") {
    items.push({ label: `${direction ?? "—"} setup created`, status: "info" });
    items.push(pivotItem);
    items.push(setupItem);
    items.push(slTpItem);
    items.push({
      label: "Waiting for price to enter the fib zone with a confirmation candle",
      status: "info",
    });
    return items;
  }

  if (eventType === "GATE_SETUP_REJECT_PIVOT_ORDER") {
    const dir =
      (detail?.["direction"] as string | undefined)?.toUpperCase() ??
      direction ??
      "—";
    const isShort = dir === "SHORT";
    const hTs = detail?.["H_ts"] as string | undefined;
    const lTs = detail?.["L_ts"] as string | undefined;
    items.push({
      label: `New pivot confirmed but ${dir} setup can't build yet`,
      status: "info",
    });
    items.push({
      label: isShort
        ? "SHORT needs a LOW that forms after the HIGH"
        : "LONG needs a HIGH that forms after the LOW",
      status: "fail",
      detail: [
        { k: "HIGH at", v: fmtTs(hTs) },
        { k: "LOW at", v: fmtTs(lTs) },
        { k: "Order needed", v: isShort ? "HIGH → LOW" : "LOW → HIGH" },
      ],
    });
    items.push({
      label: isShort
        ? "Watching for price to drop and confirm a LOW"
        : "Watching for price to rise and confirm a HIGH",
      status: "info",
    });
    return items;
  }

  if (eventType === "GATE_SETUP_REJECT_DIFF") {
    items.push({ label: `Direction: ${direction ?? "—"}`, status: "info" });
    items.push({
      label: "Pivot range must be positive",
      status: "fail",
      detail: [
        { k: "HIGH", v: `$${fmt(H)}` },
        { k: "LOW", v: `$${fmt(L)}` },
        { k: "Diff", v: `$${fmt(diff)}` },
      ],
    });
    return items;
  }

  if (eventType === "GATE_SETUP_INVALIDATED") {
    items.push({ label: `${direction ?? "—"} setup invalidated`, status: "info" });
    items.push(pivotItem);
    items.push(setupItem);
    items.push({
      label:
        side === 1
          ? "Price broke below the pivot LOW (setup invalid)"
          : "Price broke above the pivot HIGH (setup invalid)",
      status: "fail",
      detail: [
        { k: "Close", v: `$${fmt(close)}` },
        { k: "Fib 100%", v: `$${fmt(f100)}` },
      ],
    });
    return items;
  }

  if (eventType === "GATE_SETUP_EXPIRED") {
    items.push({ label: `${direction ?? "—"} setup expired`, status: "info" });
    items.push(setupItem);
    items.push({
      label: "Setup exceeded hold horizon without entry",
      status: "fail",
      detail: [
        { k: "Max hold", v: `${get<number>(detail, "max_hold_h") ?? "?"}h` },
      ],
    });
    return items;
  }

  if (eventType === "GATE_SIGNAL_STRICT_AFTER_FAIL") {
    items.push(setupItem);
    items.push({
      label: "Entry can only start on the bar AFTER setup confirmation",
      status: "fail",
      detail: [{ k: "Rule", v: "strict-after — matches research parity" }],
    });
    return items;
  }

  if (eventType === "GATE_SIGNAL_ZONE_MISS") {
    const zoneLo = side === 1 ? f786 : f382;
    const zoneHi = side === 1 ? f382 : f786;
    items.push({ label: `${direction ?? "—"} setup evaluated`, status: "info" });
    items.push(pivotItem);
    items.push(setupItem);
    items.push({ label: "Not invalidated — price still respecting setup", status: "pass" });
    items.push({
      label: "Price is in the fib retrace zone (78.6% → 38.2%)",
      status: "fail",
      detail: [
        { k: "Close", v: `$${fmt(close)}` },
        { k: "Zone low", v: `$${fmt(zoneLo)}` },
        { k: "Zone high", v: `$${fmt(zoneHi)}` },
      ],
    });
    items.push({ label: "Session filter", status: "skipped" });
    items.push({ label: "Regime filter", status: "skipped" });
    items.push({ label: "Confirmation candle", status: "skipped" });
    return items;
  }

  if (eventType === "GATE_SIGNAL_SESSION_FAIL") {
    items.push({ label: `${direction ?? "—"} setup evaluated`, status: "info" });
    items.push(setupItem);
    items.push({ label: "Not invalidated", status: "pass" });
    items.push({ label: "Price in fib zone", status: "pass" });
    items.push({
      label: "Outside allowed trading session",
      status: "fail",
      detail: [
        { k: "Allowed", v: sessionGate ?? "—" },
        { k: "NY hour", v: nyHr != null ? `${nyHr}:00` : "—" },
      ],
    });
    items.push({ label: "Regime filter", status: "skipped" });
    items.push({ label: "Confirmation candle", status: "skipped" });
    return items;
  }

  if (eventType === "GATE_SIGNAL_REGIME_FAIL") {
    items.push(setupItem);
    items.push({ label: "Not invalidated", status: "pass" });
    items.push({ label: "Price in fib zone", status: "pass" });
    items.push({ label: "Session open", status: "pass" });
    items.push({
      label: "Regime doesn't allow this direction",
      status: "fail",
      detail: [
        { k: "Required", v: regime ?? "—" },
        {
          k: "Why",
          v: regime === "any"
            ? "no daily close available yet (cold start)"
            : "D1 features don't match",
        },
      ],
    });
    items.push({ label: "Confirmation candle", status: "skipped" });
    return items;
  }

  if (eventType === "GATE_SIGNAL_CONFIRM_FAIL") {
    items.push(setupItem);
    items.push({ label: "Not invalidated", status: "pass" });
    items.push({ label: "Price in fib zone", status: "pass" });
    items.push({ label: "Session open", status: "pass" });
    items.push({ label: "Regime OK", status: "pass" });
    items.push({
      label:
        side === 1
          ? "Need bullish engulfing OR lower-wick pinbar"
          : "Need bearish engulfing OR upper-wick pinbar",
      status: "fail",
      detail: [{ k: "Reason", v: reason ?? "no confirmation pattern" }],
    });
    return items;
  }

  if (eventType === "GATE_FINALIZE_RISK_INVALID") {
    items.push(setupItem);
    items.push({
      label: "Risk must be positive (entry vs stop)",
      status: "fail",
      detail: [
        { k: "Entry", v: `$${fmt(entryPrice)}` },
        { k: "Stop", v: `$${fmt(sl)}` },
        { k: "Risk", v: `$${fmt(risk)}` },
      ],
    });
    return items;
  }

  if (eventType === "GATE_FINALIZE_RISK_PCT_CAP") {
    items.push({ label: "Signal reached final risk check", status: "pass" });
    items.push({
      label: "Risk must be ≤ 2% of entry price",
      status: "fail",
      detail: [
        { k: "Risk", v: `$${fmt(risk)}` },
        { k: "Entry", v: `$${fmt(entryPrice)}` },
        {
          k: "As %",
          v:
            risk != null && entryPrice != null
              ? `${((risk / entryPrice) * 100).toFixed(2)}%`
              : "—",
        },
        { k: "Cap", v: "2.00%" },
      ],
    });
    return items;
  }

  if (eventType === "GATE_FINALIZE_MIN_RISK_FLOOR") {
    items.push({ label: "All entry gates passed", status: "pass" });
    items.push({
      label: "Stop distance below broker-tradeable floor",
      status: "fail",
      detail: [
        { k: "Risk units", v: `$${fmt(riskUnits)}` },
        { k: "Min floor", v: `$${fmt(minRisk ?? 0.5)}` },
      ],
    });
    return items;
  }

  if (eventType === "GATE_FINALIZE_DEDUP_COLLISION") {
    items.push({ label: "All entry gates passed", status: "pass" });
    items.push({
      label: "Duplicate — same bar + side + leg already fired",
      status: "fail",
      detail: [{ k: "Policy", v: "First signal keeps the trade — this one dropped" }],
    });
    return items;
  }

  if (eventType === "GATE_SIGNAL_PASSED") {
    items.push({ label: `${direction ?? "—"} — ALL GATES PASSED`, status: "info" });
    items.push(pivotItem);
    items.push(setupItem);
    items.push({ label: "Not invalidated", status: "pass" });
    items.push({ label: "Price in fib zone", status: "pass" });
    items.push({ label: "Session open", status: "pass" });
    items.push({ label: "Regime OK", status: "pass" });
    items.push({
      label: "Confirmation candle detected",
      status: "pass",
      detail: [{ k: "Pattern", v: pattern ?? "engulfing / pinbar" }],
    });
    items.push(slTpItem);
    items.push({
      label: "Entry queued for next bar open",
      status: "info",
    });
    return items;
  }

  return [{ label: eventType, status: "info" }];
}

// ── Rendering ────────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: CheckItem["status"] }) {
  if (status === "pass")
    return (
      <span className="w-5 h-5 rounded-full bg-bull/15 border border-bull/40 flex items-center justify-center shrink-0">
        <Check size={11} className="text-bull" strokeWidth={3} />
      </span>
    );
  if (status === "fail")
    return (
      <span className="w-5 h-5 rounded-full bg-bear/15 border border-bear/40 flex items-center justify-center shrink-0 shadow-ds-glow-bear">
        <XIcon size={11} className="text-bear" strokeWidth={3} />
      </span>
    );
  if (status === "skipped")
    return (
      <span className="w-5 h-5 rounded-full bg-bg-elevated border border-line-base flex items-center justify-center shrink-0">
        <Pause size={9} className="text-ink-muted" />
      </span>
    );
  return (
    <span className="w-5 h-5 rounded-full bg-info/10 border border-info/30 flex items-center justify-center shrink-0">
      <Info size={10} className="text-info" />
    </span>
  );
}

function DetailGrid({ items }: { items: { k: string; v: string }[] }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5">
      {items.map((it, i) => (
        <div key={i} className="flex items-baseline gap-1.5">
          <span className="text-[10px] uppercase tracking-wide text-ink-muted">
            {it.k}
          </span>
          <span className="font-mono text-ds-xs text-ink-primary">{it.v}</span>
        </div>
      ))}
    </div>
  );
}

function ChecklistItem({ item, index }: { item: CheckItem; index: number }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), index * 45);
    return () => clearTimeout(t);
  }, [index]);

  const rowCls =
    item.status === "fail"
      ? "border-bear/30 bg-bear/[0.03]"
      : item.status === "pass"
      ? "border-line-subtle"
      : item.status === "skipped"
      ? "border-line-subtle opacity-60"
      : "border-info/30 bg-info/[0.03]";

  const labelCls =
    item.status === "fail"
      ? "text-bear font-medium"
      : item.status === "pass"
      ? "text-ink-primary"
      : item.status === "skipped"
      ? "text-ink-muted"
      : "text-info font-medium";

  return (
    <div
      className={`
        flex items-start gap-3 px-3 py-2 border-l-2 rounded-r-ds
        transition-all duration-300 ease-out
        ${rowCls}
        ${
          mounted
            ? "opacity-100 translate-x-0"
            : "opacity-0 -translate-x-2"
        }
      `}
    >
      <div className="pt-0.5">
        <StatusIcon status={item.status} />
      </div>
      <div className="flex-1 min-w-0">
        <div className={`text-ds-sm ${labelCls}`}>{item.label}</div>
        {item.detail && <DetailGrid items={item.detail} />}
      </div>
    </div>
  );
}

export function GateChecklist({
  eventType,
  detail,
}: {
  eventType: string;
  detail: Detail;
}) {
  const items = checklistFor(eventType, detail);
  return (
    <div className="p-3 space-y-1.5 bg-bg-base/40">
      {items.map((it, i) => (
        <ChecklistItem key={i} item={it} index={i} />
      ))}
    </div>
  );
}
