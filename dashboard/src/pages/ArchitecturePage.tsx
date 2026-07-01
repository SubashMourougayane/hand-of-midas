import { useState } from "react";
import { TrendingUp, TrendingDown } from "lucide-react";

/**
 * Architecture — visual rulebook for A (LONG) and D (SHORT) setups.
 * Two-tab layout. Each tab shows the full decision flow from pivot detection
 * to entry to exit as a top-down diagram.
 */
export function ArchitecturePage() {
  const [tab, setTab] = useState<"long" | "short">("long");
  return (
    <div className="h-full overflow-auto p-4">
      <div className="max-w-[1400px] mx-auto space-y-4">
        <header className="flex items-baseline justify-between">
          <div>
            <h1 className="text-ds-2xl font-semibold text-ink-primary tracking-tight">
              Strategy Rulebook
            </h1>
            <p className="text-ds-sm text-ink-muted mt-1">
              Fib V2 intraday · M15 base · lb=3 pivot confirmation · PTP+1R · $0.65 broker cost
            </p>
          </div>
          <div className="flex items-center gap-1 bg-bg-elevated border border-line-base rounded-ds p-1">
            <TabBtn
              active={tab === "long"}
              onClick={() => setTab("long")}
              tone="bull"
              icon={<TrendingUp size={14} />}
              label="A · LONG"
              sub="12h hold · london_ny"
            />
            <TabBtn
              active={tab === "short"}
              onClick={() => setTab("short")}
              tone="bear"
              icon={<TrendingDown size={14} />}
              label="D · SHORT"
              sub="24h hold · all sessions"
            />
          </div>
        </header>

        {tab === "long" ? <LongFlow /> : <ShortFlow />}

        <SharedRules />
      </div>
    </div>
  );
}

function TabBtn({
  active, onClick, tone, icon, label, sub,
}: {
  active: boolean; onClick: () => void; tone: "bull" | "bear";
  icon: React.ReactNode; label: string; sub: string;
}) {
  const toneCls = active
    ? tone === "bull"
      ? "bg-bull/15 text-bull border-bull/40"
      : "bg-bear/15 text-bear border-bear/40"
    : "text-ink-muted hover:text-ink-secondary border-transparent";
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-ds-sm border ${toneCls} flex items-center gap-2 transition-colors duration-ds`}
    >
      {icon}
      <div className="text-left leading-tight">
        <div className="font-semibold text-ds-sm">{label}</div>
        <div className="text-ds-xs opacity-70">{sub}</div>
      </div>
    </button>
  );
}

// ── FLOW BLOCKS ──

function Step({
  n,
  title,
  desc,
  tone = "neutral",
  detail,
  formula,
}: {
  n: string;
  title: string;
  desc: string;
  tone?: "neutral" | "info" | "bull" | "bear" | "warn" | "success";
  detail?: React.ReactNode;
  formula?: string;
}) {
  const toneMap = {
    neutral: "border-line-base bg-bg-elevated",
    info: "border-info/40 bg-info/[0.05]",
    bull: "border-bull/40 bg-bull/[0.05]",
    bear: "border-bear/40 bg-bear/[0.05]",
    warn: "border-warn/40 bg-warn/[0.05]",
    success: "border-brass/50 bg-brass/[0.08] shadow-ds-glow-bull",
  };
  const nBg = {
    neutral: "bg-line-base text-ink-primary",
    info: "bg-info text-bg-base",
    bull: "bg-bull text-bg-base",
    bear: "bg-bear text-bg-base",
    warn: "bg-warn text-bg-base",
    success: "bg-brass text-bg-base",
  };
  return (
    <div className={`relative border rounded-ds p-4 ${toneMap[tone]}`}>
      <div className="flex items-start gap-3">
        <span className={`shrink-0 w-8 h-8 rounded-full ${nBg[tone]} flex items-center justify-center font-bold text-ds-sm`}>
          {n}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-ds-md font-semibold text-ink-primary mb-0.5">{title}</div>
          <div className="text-ds-sm text-ink-secondary">{desc}</div>
          {formula && (
            <div className="mt-2 font-mono text-ds-xs bg-bg-input border border-line-subtle rounded-ds-sm px-2 py-1 text-ink-primary">
              {formula}
            </div>
          )}
          {detail && <div className="mt-2 text-ds-xs text-ink-muted">{detail}</div>}
        </div>
      </div>
    </div>
  );
}

function Arrow({ tone = "neutral" }: { tone?: "neutral" | "bull" | "bear" }) {
  const cls =
    tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-muted";
  return (
    <div className="flex justify-center py-1">
      <div className={`${cls} text-ds-md`}>↓</div>
    </div>
  );
}

function GateGroup({
  title,
  tone,
  gates,
}: {
  title: string;
  tone: "bull" | "bear";
  gates: { label: string; ok: string; fail: string }[];
}) {
  const border = tone === "bull" ? "border-bull/30" : "border-bear/30";
  return (
    <div className={`border ${border} rounded-ds p-4 bg-bg-surface`}>
      <div className="text-ds-sm font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        {title}
      </div>
      <div className="space-y-2">
        {gates.map((g, i) => (
          <div key={i} className="grid grid-cols-12 gap-3 items-baseline">
            <div className="col-span-3 text-ds-sm text-ink-primary font-medium leading-snug">
              {g.label}
            </div>
            <div className="col-span-5 text-ds-xs text-bull grid grid-cols-[14px_1fr] gap-1 leading-snug">
              <span className="text-center">✓</span>
              <span>{g.ok}</span>
            </div>
            <div className="col-span-4 text-ds-xs text-bear grid grid-cols-[14px_1fr] gap-1 leading-snug">
              <span className="text-center">✗</span>
              <span>{g.fail}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── LONG FLOW ──

function LongFlow() {
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-7 space-y-0">
        <div className="text-ds-md font-semibold text-bull mb-3 tracking-wide">
          A LEG · LONG ENTRY FLOW
        </div>

        <Step
          n="1"
          title="Pivot detection"
          tone="info"
          desc="Scan M15 bars for confirmed HIGH + LOW pivots. Confirmation = 3 bars either side (lb=3)."
          formula="LOW = min(3 bars left, center, 3 bars right)  ·  HIGH = max(…)"
          detail={<>Emits <code className="text-info">GATE_PIVOT_DETECTED</code> when new pivot confirms 3 bars after its actual formation.</>}
        />
        <Arrow tone="bull" />

        <Step
          n="2"
          title="Pivot ordering check (LONG-specific)"
          tone="bull"
          desc="For a LONG setup, HIGH must confirm AFTER LOW chronologically."
          formula="H_ts > L_ts    (market bottomed, then made new high, now expecting retrace back down)"
          detail={<>Fail → <code className="text-bear">GATE_SETUP_REJECT_PIVOT_ORDER</code></>}
        />
        <Arrow tone="bull" />

        <Step
          n="3"
          title="Fib retrace setup built"
          tone="info"
          desc="From H and L, compute fib levels. Setup lives until invalidated or expired (12h)."
          formula="fib_100 = LOW  ·  fib_382 = H − 0.382×Δ  ·  fib_786 = H − 0.786×Δ  ·  SL = LOW − 0.02×Δ  ·  TP = H + 2.618×Δ"
        />
        <Arrow tone="bull" />

        <Step
          n="4"
          title="Wait for retrace INTO zone"
          desc="Each M15 close checks: is price back inside the 78.6% → 38.2% retrace band?"
          formula="fib_786 ≤ bar.close ≤ fib_382"
          detail={<>Zone miss → <code className="text-bear">GATE_SIGNAL_ZONE_MISS</code> (repeats per bar until in-zone or invalidated)</>}
        />
        <Arrow tone="bull" />

        <GateGroup
          title="Entry gate stack"
          tone="bull"
          gates={[
            {
              label: "Invalidation",
              ok: "close ≥ fib_100 (LOW) — setup still valid",
              fail: "close < LOW → setup killed",
            },
            {
              label: "Zone hit",
              ok: "close inside [78.6%, 38.2%]",
              fail: "close outside — waits next bar",
            },
            {
              label: "Session",
              ok: "NY hour in [3, 17) → London or NY open",
              fail: "outside window — waits",
            },
            {
              label: "Regime",
              ok: "D1 features finite (any regime)",
              fail: "no daily close yet — waits",
            },
            {
              label: "Confirmation candle",
              ok: "bullish engulf OR lower-wick pinbar (wick > 50% of range)",
              fail: "no pattern — waits next bar",
            },
            {
              label: "Strict-after",
              ok: "current bar strictly after setup_confirm_ts",
              fail: "same bar as confirm — skip",
            },
          ]}
        />
        <Arrow tone="bull" />

        <Step
          n="5"
          title="Order queued for NEXT bar open"
          tone="success"
          desc="All gates pass → GATE_SIGNAL_PASSED. Entry price = next M15 open (research-parity)."
          formula="entry = next_bar.open  ·  risk = entry − SL  ·  qty = 1.5% × equity / risk / contract_size"
        />
        <Arrow tone="bull" />

        <GateGroup
          title="Final safety gates"
          tone="bull"
          gates={[
            {
              label: "Risk sanity",
              ok: "0 < risk < 2% × entry",
              fail: "risk ≤ 0 or > 2% → reject",
            },
            {
              label: "Min risk floor",
              ok: "risk_units ≥ $0.50 (XAU broker-tradeable)",
              fail: "risk too tight — reject",
            },
            {
              label: "Dedup",
              ok: "(entry_ts, side, leg) not seen before",
              fail: "duplicate → reject",
            },
            {
              label: "Broker submit",
              ok: "DWX bridge accepts order → filled at market",
              fail: "spread > $0.50 or kill-switch → reject",
            },
          ]}
        />
        <Arrow tone="bull" />

        <Step
          n="6"
          title="Bracket walker — exit logic"
          tone="bull"
          desc="Each subsequent M15 bar walks brackets against high/low."
          detail={
            <ul className="list-disc pl-4 space-y-0.5">
              <li>TP hit (close ≥ TP) → close full at TP</li>
              <li>SL hit (close ≤ SL) → close full at SL</li>
              <li>+1R hit (partial TP) → close 50% at +1R, move SL to breakeven for rest</li>
              <li>12h elapsed (48 M15 bars) → TIMEOUT exit at bar close</li>
            </ul>
          }
        />
      </div>

      <aside className="col-span-12 lg:col-span-5 space-y-3">
        <div className="text-ds-md font-semibold text-transparent mb-3 select-none" aria-hidden>
          .
        </div>
        <div className="border border-bull/40 rounded-ds p-4 bg-bull/[0.05]">
          <div className="text-ds-md font-semibold text-bull mb-2">Locked config · A</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-ds-sm">
            <dt className="text-ink-muted">Direction</dt><dd className="text-ink-primary">LONG</dd>
            <dt className="text-ink-muted">Base TF</dt><dd className="text-ink-primary">M15</dd>
            <dt className="text-ink-muted">Pivot lookback</dt><dd className="text-ink-primary">lb = 3</dd>
            <dt className="text-ink-muted">Session</dt><dd className="text-ink-primary">london_ny (NY 3-17)</dd>
            <dt className="text-ink-muted">Regime</dt><dd className="text-ink-primary">any</dd>
            <dt className="text-ink-muted">Max hold</dt><dd className="text-ink-primary">12h (48 bars)</dd>
            <dt className="text-ink-muted">SL buffer</dt><dd className="text-ink-primary">0.02 × Δ below LOW</dd>
            <dt className="text-ink-muted">TP extension</dt><dd className="text-ink-primary">2.618 × Δ above HIGH</dd>
            <dt className="text-ink-muted">Partial TP</dt><dd className="text-ink-primary">50% @ +1R → SL→BE</dd>
            <dt className="text-ink-muted">Min risk floor</dt><dd className="text-ink-primary">$0.50 / oz</dd>
            <dt className="text-ink-muted">Cost model</dt><dd className="text-ink-primary">$0.65 / trade</dd>
          </dl>
        </div>

        <PriceDiagram side="long" />
      </aside>
    </div>
  );
}

// ── SHORT FLOW ──

function ShortFlow() {
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-7 space-y-0">
        <div className="text-ds-md font-semibold text-bear mb-3 tracking-wide">
          D LEG · SHORT ENTRY FLOW
        </div>

        <Step
          n="1"
          title="Pivot detection"
          tone="info"
          desc="Scan M15 bars for confirmed HIGH + LOW pivots. Confirmation = 3 bars either side (lb=3)."
          formula="HIGH = max(3 bars left, center, 3 bars right)  ·  LOW = min(…)"
          detail={<>Emits <code className="text-info">GATE_PIVOT_DETECTED</code> when new pivot confirms.</>}
        />
        <Arrow tone="bear" />

        <Step
          n="2"
          title="Pivot ordering check (SHORT-specific)"
          tone="bear"
          desc="For a SHORT setup, LOW must confirm AFTER HIGH chronologically."
          formula="L_ts > H_ts    (market peaked, then made new low, now expecting retrace back up)"
          detail={<>Fail → <code className="text-bear">GATE_SETUP_REJECT_PIVOT_ORDER</code></>}
        />
        <Arrow tone="bear" />

        <Step
          n="3"
          title="Fib retrace setup built"
          tone="info"
          desc="From H and L, compute fib levels. Setup lives until invalidated or expired (24h)."
          formula="fib_100 = HIGH  ·  fib_382 = L + 0.382×Δ  ·  fib_786 = L + 0.786×Δ  ·  SL = HIGH + 0.02×Δ  ·  TP = L − 2.618×Δ"
        />
        <Arrow tone="bear" />

        <Step
          n="4"
          title="Wait for retrace INTO zone"
          desc="Each M15 close checks: is price back inside the 38.2% → 78.6% retrace band?"
          formula="fib_382 ≤ bar.close ≤ fib_786"
          detail={<>Zone miss → <code className="text-bear">GATE_SIGNAL_ZONE_MISS</code> (repeats per bar until in-zone or invalidated)</>}
        />
        <Arrow tone="bear" />

        <GateGroup
          title="Entry gate stack"
          tone="bear"
          gates={[
            {
              label: "Invalidation",
              ok: "close ≤ fib_100 (HIGH) — setup still valid",
              fail: "close > HIGH → setup killed",
            },
            {
              label: "Zone hit",
              ok: "close inside [38.2%, 78.6%]",
              fail: "close outside — waits next bar",
            },
            {
              label: "Session",
              ok: "all sessions allowed (D leg has no session filter)",
              fail: "n/a — always passes",
            },
            {
              label: "Regime",
              ok: "D1 features finite (any regime)",
              fail: "no daily close yet — waits",
            },
            {
              label: "Confirmation candle",
              ok: "bearish engulf OR upper-wick pinbar (wick > 50% of range)",
              fail: "no pattern — waits next bar",
            },
            {
              label: "Strict-after",
              ok: "current bar strictly after setup_confirm_ts",
              fail: "same bar as confirm — skip",
            },
          ]}
        />
        <Arrow tone="bear" />

        <Step
          n="5"
          title="Order queued for NEXT bar open"
          tone="success"
          desc="All gates pass → GATE_SIGNAL_PASSED. Entry price = next M15 open."
          formula="entry = next_bar.open  ·  risk = SL − entry  ·  qty = 1.5% × equity / risk / contract_size"
        />
        <Arrow tone="bear" />

        <GateGroup
          title="Final safety gates"
          tone="bear"
          gates={[
            {
              label: "Risk sanity",
              ok: "0 < risk < 2% × entry",
              fail: "risk ≤ 0 or > 2% → reject",
            },
            {
              label: "Min risk floor",
              ok: "risk_units ≥ $0.50 (XAU broker-tradeable)",
              fail: "risk too tight — reject",
            },
            {
              label: "Dedup",
              ok: "(entry_ts, side, leg) not seen before",
              fail: "duplicate → reject",
            },
            {
              label: "Broker submit",
              ok: "DWX bridge accepts order → filled at market",
              fail: "spread > $0.50 or kill-switch → reject",
            },
          ]}
        />
        <Arrow tone="bear" />

        <Step
          n="6"
          title="Bracket walker — exit logic"
          tone="bear"
          desc="Each subsequent M15 bar walks brackets against high/low."
          detail={
            <ul className="list-disc pl-4 space-y-0.5">
              <li>TP hit (close ≤ TP) → close full at TP</li>
              <li>SL hit (close ≥ SL) → close full at SL</li>
              <li>+1R hit (partial TP) → close 50% at +1R, move SL to breakeven for rest</li>
              <li>24h elapsed (96 M15 bars) → TIMEOUT exit at bar close</li>
            </ul>
          }
        />
      </div>

      <aside className="col-span-12 lg:col-span-5 space-y-3">
        <div className="text-ds-md font-semibold text-transparent mb-3 select-none" aria-hidden>
          .
        </div>
        <div className="border border-bear/40 rounded-ds p-4 bg-bear/[0.05]">
          <div className="text-ds-md font-semibold text-bear mb-2">Locked config · D</div>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-ds-sm">
            <dt className="text-ink-muted">Direction</dt><dd className="text-ink-primary">SHORT</dd>
            <dt className="text-ink-muted">Base TF</dt><dd className="text-ink-primary">M15</dd>
            <dt className="text-ink-muted">Pivot lookback</dt><dd className="text-ink-primary">lb = 3</dd>
            <dt className="text-ink-muted">Session</dt><dd className="text-ink-primary">all (24/7)</dd>
            <dt className="text-ink-muted">Regime</dt><dd className="text-ink-primary">any</dd>
            <dt className="text-ink-muted">Max hold</dt><dd className="text-ink-primary">24h (96 bars)</dd>
            <dt className="text-ink-muted">SL buffer</dt><dd className="text-ink-primary">0.02 × Δ above HIGH</dd>
            <dt className="text-ink-muted">TP extension</dt><dd className="text-ink-primary">2.618 × Δ below LOW</dd>
            <dt className="text-ink-muted">Partial TP</dt><dd className="text-ink-primary">50% @ +1R → SL→BE</dd>
            <dt className="text-ink-muted">Min risk floor</dt><dd className="text-ink-primary">$0.50 / oz</dd>
            <dt className="text-ink-muted">Cost model</dt><dd className="text-ink-primary">$0.65 / trade</dd>
          </dl>
        </div>

        <PriceDiagram side="short" />
      </aside>
    </div>
  );
}

// ── Price ladder mini-diagram ──

function PriceDiagram({ side }: { side: "long" | "short" }) {
  // Positions rendered top-to-bottom
  const isLong = side === "long";
  const rows = isLong
    ? [
        { label: "TP  (H + 2.618·Δ)", color: "text-bull", weight: "font-semibold", bar: "bg-bull" },
        { label: "HIGH pivot", color: "text-info", weight: "font-medium", bar: "bg-info" },
        { label: "Zone hi  (H − 0.382·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "Zone lo  (H − 0.786·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "LOW pivot / fib_100", color: "text-warn", weight: "font-medium", bar: "bg-warn" },
        { label: "SL  (LOW − 0.02·Δ)", color: "text-bear", weight: "font-semibold", bar: "bg-bear" },
      ]
    : [
        { label: "SL  (HIGH + 0.02·Δ)", color: "text-bear", weight: "font-semibold", bar: "bg-bear" },
        { label: "HIGH pivot / fib_100", color: "text-warn", weight: "font-medium", bar: "bg-warn" },
        { label: "Zone hi  (L + 0.786·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "Zone lo  (L + 0.382·Δ)", color: "text-ink-primary", weight: "", bar: "bg-brass/60" },
        { label: "LOW pivot", color: "text-info", weight: "font-medium", bar: "bg-info" },
        { label: "TP  (LOW − 2.618·Δ)", color: "text-bull", weight: "font-semibold", bar: "bg-bull" },
      ];
  return (
    <div className="border border-line-base rounded-ds p-4 bg-bg-surface">
      <div className="text-ds-sm font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Price ladder
      </div>
      <div className="space-y-1">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2 text-ds-xs">
            <span className={`w-1 h-4 ${r.bar} rounded-full`} />
            <span className={`${r.color} ${r.weight} font-mono`}>{r.label}</span>
          </div>
        ))}
        <div className="mt-2 pt-2 border-t border-line-subtle text-ds-xs text-ink-muted">
          Zone shaded → strategy waits here for {isLong ? "bullish" : "bearish"} confirmation candle.
        </div>
      </div>
    </div>
  );
}

// ── Shared cross-strategy notes ──

function SharedRules() {
  return (
    <section className="border border-line-subtle rounded-ds bg-bg-surface p-4 mt-6">
      <div className="text-ds-md font-semibold text-ink-primary mb-3 uppercase tracking-wide">
        Shared rules (both legs)
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <RuleCard
          title="Causality — no look-ahead"
          points={[
            "Pivot confirmed 3 bars AFTER center — no peek at future.",
            "Regime uses D1 features from LAST closed day (shift(1)).",
            "Entry price = NEXT bar's open, not signal bar's close.",
            "MFE/MAE tracked bar-by-bar close, never intra-bar.",
          ]}
        />
        <RuleCard
          title="Sizing — Model B asymmetric monthly"
          points={[
            "risk_$ = 1.5% × current equity per trade.",
            "Skim profits at month-end back to start balance.",
            "Eat losses — trade smaller next month (no claw-back).",
            "Never wipes — 0 wipeouts in 21yr backtest.",
          ]}
        />
        <RuleCard
          title="Safety brakes"
          points={[
            "max_lot cap: 0.01 lot (paper-live default; production tune).",
            "max_open_positions: 4 concurrent (research validated).",
            "max_spread: reject if spread > $0.50 at submit time.",
            "kill-switch file: touch LIVE_DISABLED → halt all live entries.",
            "demo-only enforcement: refuses non-demo accounts by default.",
          ]}
        />
        <RuleCard
          title="Dedup + friction"
          points={[
            "One entry per (bar_ts, side, leg) — first signal wins.",
            "Multi-pivot stacking on same bar → drop later duplicates.",
            "Min risk floor $0.50/oz — reject broker-untradeable stops.",
            "Same-bar opposite direction allowed (A long + D short = hedge).",
          ]}
        />
        <RuleCard
          title="Expected numbers (research @ 1.5% Model B, $5k start)"
          points={[
            "Net $ lifetime: +$816,401 (21 yrs)",
            "Avg / year: +$38,876",
            "Best year: +$124,648 (2013)",
            "Worst year: +$4,186 (2007) — still positive",
            "Positive years: 21/21",
            "Positive months: 174/244 (71%)",
            "Wipeouts: 0",
          ]}
        />
        <RuleCard
          title="Audit gates applied"
          points={[
            "15-point audit POST-DEDUP: ALL PASS",
            "Cross-symbol survival: XAU + EUR only",
            "Delay stress +1/+5/+10 bars: edge stays or improves",
            "Cost stress: alive to $0.80/trade, dead at $1.00 — JM at $0.65 safe",
            "IS/OOS ratio 0.96–1.16 — no overfit",
          ]}
        />
      </div>
    </section>
  );
}

function RuleCard({ title, points }: { title: string; points: string[] }) {
  return (
    <div className="border border-line-subtle rounded-ds-sm p-3 bg-bg-elevated">
      <div className="text-ds-sm font-semibold text-ink-primary mb-2">{title}</div>
      <ul className="space-y-1">
        {points.map((p, i) => (
          <li key={i} className="flex items-start gap-2 text-ds-xs text-ink-secondary">
            <span className="text-brass mt-0.5">•</span>
            <span>{p}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
