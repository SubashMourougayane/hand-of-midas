"use client";
import { useState, useEffect } from "react";
import {
  Database, TrendingUp, Layers, Shield,
  Activity, Zap, BarChart2, Target, GitBranch, Clock, Radio,
} from "lucide-react";
import { PageHeader, Tabs as UiTabs } from "@/components/ui";

type Tab = "overview" | "strategies" | "execution" | "risk" | "data" | "schedule";

const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Overview", icon: Layers },
  { id: "strategies", label: "Strategies", icon: TrendingUp },
  { id: "execution", label: "Execution", icon: Zap },
  { id: "risk", label: "Risk", icon: Shield },
  { id: "data", label: "Data", icon: Database },
  { id: "schedule", label: "Schedule", icon: Clock },
];

// Brass-aware palette for the inline diagrams. Replaces the legacy
// hardcoded greens / blues / yellows scattered through the tab bodies.
const ARCH = {
  brass: "var(--color-brass)",
  brassHi: "var(--color-brass-hi)",
  win: "var(--color-win)",
  loss: "var(--color-loss)",
  info: "var(--color-info)",
  warn: "var(--color-warn)",
  text: "var(--color-text)",
  dim: "var(--color-text-dim)",
  muted: "var(--color-text-muted)",
  border: "var(--color-border)",
  surface1: "var(--color-surface-1)",
  surface2: "var(--color-surface-2)",
};

export default function ArchitecturePage() {
  const [active, setActive] = useState<Tab>("overview");

  return (
    <div className="p-3 sm:p-6 max-w-[1280px] mx-auto" style={{ background: "var(--color-bg)" }}>
      <style>{animationStyles}</style>

      <PageHeader
        title="System Architecture"
        description="Hand Of Midas — Multi-asset algorithmic trading engine"
      />

      <UiTabs.Root value={active} onValueChange={(v) => setActive(v as Tab)} className="mb-4">
        <UiTabs.List className="overflow-x-auto">
          {tabs.map(({ id, label, icon: Icon }) => (
            <UiTabs.Trigger key={id} value={id}>
              <Icon className="w-3.5 h-3.5 mr-1.5 inline-block align-[-2px]" />
              <span>{label}</span>
            </UiTabs.Trigger>
          ))}
        </UiTabs.List>
      </UiTabs.Root>

      {active === "overview" && <OverviewTab />}
      {active === "strategies" && <StrategiesTab />}
      {active === "execution" && <ExecutionTab />}
      {active === "risk" && <RiskTab />}
      {active === "data" && <DataTab />}
      {active === "schedule" && <ScheduleTab />}
    </div>
  );
}

// ─── SHARED COMPONENTS ────────────────────────────────────────────────────────

function FlowNode({ label, sub, color, delay = 0 }: {
  label: string; sub?: string; color?: string; delay?: number;
}) {
  const c = color ?? ARCH.brass;
  return (
    <div className="arch-node relative px-5 py-4 text-center min-w-[130px]" style={{
      background: `color-mix(in srgb, ${c} 10%, transparent)`,
      border: `1px solid ${c}`,
      animationDelay: `${delay}s`,
      borderRadius: "5px",
      boxShadow: `0 0 16px -8px ${c}`,
    }}>
      <div className="text-[13px] font-semibold tracking-tight" style={{ color: c }}>{label}</div>
      {sub && <div className="text-[11px] mt-1 num" style={{ color: ARCH.muted }}>{sub}</div>}
    </div>
  );
}

function FlowArrow({ delay = 0, label }: { delay?: number; label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center mx-2" style={{ animationDelay: `${delay}s` }}>
      <div
        className="arch-arrow h-[2px] w-10"
        style={{ background: `linear-gradient(90deg, ${ARCH.muted}, ${ARCH.brass})` }}
      />
      {label && <span className="text-[10px] mt-1 num" style={{ color: ARCH.muted }}>{label}</span>}
    </div>
  );
}

function FlowArrowDown({ delay = 0, label }: { delay?: number; label?: string }) {
  return (
    <div className="flex flex-col items-center py-2" style={{ animationDelay: `${delay}s` }}>
      <div
        className="arch-arrow-down w-[2px] h-8"
        style={{ background: `linear-gradient(180deg, ${ARCH.muted}, ${ARCH.brass})` }}
      />
      {label && <span className="text-[10px] mt-1 num" style={{ color: ARCH.muted }}>{label}</span>}
    </div>
  );
}

function PulseOrb({ color, size = 10 }: { color?: string; size?: number }) {
  const c = color ?? ARCH.brass;
  return (
    <span className="arch-pulse inline-block rounded-full"
      style={{ width: size, height: size, background: c, boxShadow: `0 0 10px ${c}` }} />
  );
}

function MetricBar({ label, value, max, color }: { label: string; value: number; max: number; color?: string }) {
  const c = color ?? ARCH.brass;
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="mb-3">
      <div className="flex justify-between text-[12px] mb-1">
        <span style={{ color: ARCH.dim }}>{label}</span>
        <span className="num font-semibold" style={{ color: c }}>{value}</span>
      </div>
      <div className="h-1.5 w-full rounded-full" style={{ background: ARCH.surface2 }}>
        <div className="arch-bar h-full rounded-full" style={{ width: `${pct}%`, background: c }} />
      </div>
    </div>
  );
}

// ─── TAB: OVERVIEW ────────────────────────────────────────────────────────────

function OverviewTab() {
  return (
    <div className="space-y-6">
      <div className="p-3 sm:p-6 rounded-lg overflow-x-auto" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-5" style={{ color: "var(--color-brass-hi)" }}>
          COMPLETE SYSTEM FLOW — LONDON + NY SESSION (08:00-20:00 UTC)
        </div>

        <div className="min-w-[500px]">
        {/* Row 1: Data Source */}
        <div className="flex flex-wrap items-center justify-center gap-2 mb-2">
          <FlowNode label="OANDA API" sub="H1 + M3 + Daily" color="#e8c300" delay={0} />
          <FlowArrow delay={0.2} label="candles" />
          <FlowNode label="Scheduler" sub="every 3 min" color="#4da6ff" delay={0.4} />
          <FlowArrow delay={0.6} label="analyze" />
          <FlowNode label="Alpha-Sweep" sub="sweep + engulf" color="#00e87b" delay={0.8} />
        </div>

        <div className="flex justify-center"><FlowArrowDown delay={1.0} label="signal?" /></div>

        {/* Row 2: Filters */}
        <div className="flex flex-wrap items-center justify-center gap-2 mb-2">
          <FlowNode label="DD Protection" sub="pause / halve" color="#ff3e3e" delay={1.2} />
          <FlowArrow delay={1.4} label="pass?" />
          <FlowNode label="Position Sizing" sub="4% risk × mult" color="#4da6ff" delay={1.6} />
          <FlowArrow delay={1.8} label="units" />
          <FlowNode label="OANDA Order" sub="market + SL + TP" color="#00e87b" delay={2.0} />
        </div>

        <div className="flex justify-center"><FlowArrowDown delay={2.2} label="filled" /></div>

        {/* Row 3: Monitor */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <FlowNode label="Price Stream" sub="tick-by-tick" color="#e8c300" delay={2.4} />
          <FlowArrow delay={2.6} label="50% TP?" />
          <FlowNode label="Break-Even" sub="SL → entry" color="#ff8c00" delay={2.8} />
          <FlowArrow delay={3.0} label="wait" />
          <FlowNode label="Exit Detect" sub="SL / TP / MaxHold" color="#ff3e3e" delay={3.2} />
        </div>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {[
          { label: "INSTRUMENTS", value: "2", sub: "XAU/USD + BCO/USD", color: "#00e87b" },
          { label: "STRATEGIES", value: "3", sub: "Alpha + MeanRev + Cross", color: "#4da6ff" },
          { label: "BACKTEST (20yr)", value: "$640K", sub: "Gold $325K + Oil $315K", color: "#e8c300" },
          { label: "SCAN INTERVAL", value: "3 min", sub: "London + NY session", color: "#ff3e3e" },
        ].map(({ label, value, sub, color }) => (
          <div key={label} className="p-5 text-center arch-fade-in rounded" style={{ background: "var(--color-surface-1)", border: `1px solid ${color}30` }}>
            <PulseOrb color={color} size={12} />
            <div className="text-xl font-bold mt-3" style={{ color }}>{value}</div>
            <div className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>{label}</div>
            <div className="text-xs" style={{ color: "#8b95a5" }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* Architecture summary */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          ARCHITECTURE — SEPARATE BACKENDS, SHARED FRONTEND
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div className="p-4" style={{ background: "#080a0f", border: "1.5px solid #e8c300" }}>
            <div className="text-xs font-bold" style={{ color: "#e8c300" }}>GOLD BACKEND :5053</div>
            <div className="text-xs mt-2 space-y-1" style={{ color: "var(--color-text-muted)" }}>
              <div>Alpha-Sweep (London)</div>
              <div>Mean-Rev (Daily dip)</div>
              <div>Cross-Market (6 instruments)</div>
              <div>Position monitor (1 min)</div>
              <div>Price stream (XAU_USD)</div>
            </div>
          </div>
          <div className="p-4" style={{ background: "#080a0f", border: "1.5px solid #4fc3f7" }}>
            <div className="text-xs font-bold" style={{ color: "#4fc3f7" }}>OIL BACKEND :5054</div>
            <div className="text-xs mt-2 space-y-1" style={{ color: "var(--color-text-muted)" }}>
              <div>Alpha-Sweep (London)</div>
              <div>Position monitor (1 min)</div>
              <div>Price stream (BCO_USD)</div>
              <div>Independent DD state</div>
            </div>
          </div>
          <div className="p-4" style={{ background: "#080a0f", border: "1.5px solid #00e87b" }}>
            <div className="text-xs font-bold" style={{ color: "#00e87b" }}>SHARED</div>
            <div className="text-xs mt-2 space-y-1" style={{ color: "var(--color-text-muted)" }}>
              <div>Frontend :3001 (Next.js)</div>
              <div>OANDA account (GBP)</div>
              <div>PostgreSQL (golddigger)</div>
              <div>fill_model.py (backtest parity)</div>
              <div>Telegram notifications</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── TAB: STRATEGIES ──────────────────────────────────────────────────────────

function StrategiesTab() {
  return (
    <div className="space-y-6">
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          3 STRATEGIES — SIGNAL GENERATION LOGIC
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            {
              name: "ALPHA-SWEEP", instruments: "XAU/USD + BCO/USD", risk: "4%",
              conditions: ["Asia range > threshold", "London sweeps Asia H/L", "Daily bias confirms", "M3 engulfing within 2hrs", "Not first bar after sweep"],
              color: "#4fc3f7", stats: "PF 3.40 Gold / 8.31 Oil",
              timing: "08:00-20:00 UTC, every 3 min",
            },
            {
              name: "MEAN-REV", instruments: "XAU/USD only", risk: "3%",
              conditions: ["RSI(14) < 30", "Price < 20-day MA - 0.5×ATR", "Gold above 50-day MA", "Max 1 open position", "Condition exit on RSI > 50"],
              color: "#00e87b", stats: "PF 2.80, 55% WR",
              timing: "22:00 UTC daily",
            },
            {
              name: "CROSS-MARKET", instruments: "XAU/USD only", risk: "2%",
              conditions: ["6-instrument consensus ≥ 4/11", "DXY, US10Y, SPX, Silver, Oil, US2Y", "2-day gap between signals", "Max 1 open position", "20-day max hold"],
              color: "#ffd54f", stats: "PF 2.10, 52% WR",
              timing: "22:00 UTC daily",
            },
          ].map(({ name, instruments, risk, conditions, color, stats, timing }) => (
            <div key={name} className="p-5 arch-fade-in" style={{ background: "#080a0f", border: `1.5px solid ${color}` }}>
              <div className="text-center mb-4">
                <div className="text-sm font-bold" style={{ color }}>{name}</div>
                <div className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>{instruments}</div>
                <div className="flex gap-2 justify-center mt-2">
                  <span className="text-xs px-2 py-0.5" style={{ background: `${color}20`, color }}>Risk: {risk}</span>
                  <span className="text-xs px-2 py-0.5" style={{ background: "var(--color-surface-2)", color: "var(--color-text-muted)" }}>{stats}</span>
                </div>
              </div>
              <div className="space-y-1.5 mb-3">
                {conditions.map((c, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
                    <span className="text-xs" style={{ color: "#8b949e" }}>{c}</span>
                  </div>
                ))}
              </div>
              <div className="text-xs pt-2" style={{ borderTop: "1px solid #1a1f27", color: "#8b95a5" }}>
                <Clock className="w-3 h-3 inline mr-1" />{timing}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Backtest results comparison */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          20-YEAR BACKTEST RESULTS ($5K/year capital)
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { label: "Gold Combined", trades: 1238, wr: "63.2%", pf: "3.83", pnl: "$325K", color: "#e8c300" },
            { label: "Oil Alpha-Sweep", trades: 846, wr: "74.0%", pf: "7.95", pnl: "$315K", color: "#4fc3f7" },
            { label: "Max Drawdown", trades: 0, wr: "-19%", pf: "Gold", pnl: "-14.9% Oil", color: "#ff3e3e" },
            { label: "Combined Total", trades: 2084, wr: "65.4%", pf: "4.50", pnl: "$640K", color: "#00e87b" },
          ].map(({ label, trades, wr, pf, pnl, color }) => (
            <div key={label} className="p-4 text-center" style={{ background: "#080a0f", border: `1px solid ${color}30` }}>
              <div className="text-xs font-bold" style={{ color }}>{label}</div>
              {trades > 0 && <div className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>{trades} trades</div>}
              <div className="text-lg font-bold mt-2" style={{ color }}>{pnl}</div>
              <div className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>WR: {wr} | PF: {pf}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── TAB: EXECUTION ───────────────────────────────────────────────────────────

function ExecutionTab() {
  return (
    <div className="space-y-6">
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          TRADE LIFECYCLE — FROM SIGNAL TO EXIT
        </div>

        <div className="relative">
          <div className="absolute left-6 top-0 bottom-0 w-[2px]" style={{ background: "var(--color-border)" }} />

          {[
            { time: "T+0", event: "SIGNAL DETECTED", detail: "Asia sweep + M3 engulfing confirmed + daily bias match", color: "#e8c300" },
            { time: "T+0", event: "DD CHECK", detail: "consecutive_losses < 5? pause_counter = 0? Gold above 50MA?", color: "#ff3e3e" },
            { time: "T+0", event: "POSITION SIZING", detail: "equity × risk% × risk_mult / sl_distance = units (capped at MAX)", color: "#4da6ff" },
            { time: "T+0", event: "ORDER PLACED", detail: "OANDA market order with SL + TP attached (GTC)", color: "#00e87b" },
            { time: "T+0", event: "ENTRY FILLED", detail: "Fill price, trade_id persisted to DB + Telegram notification", color: "#00e87b" },
            { time: "T+1m", event: "POSITION MONITOR", detail: "Every 60s: is trade still open on OANDA? Detect SL/TP fills", color: "#4da6ff" },
            { time: "T+?", event: "BREAK-EVEN", detail: "Price reaches 50% to TP → SL moved to entry +$0.30 (Gold) / +$0.01 (Oil)", color: "#ff8c00" },
            { time: "T+?", event: "EXIT DETECTED", detail: "SL hit / TP hit / MAX_HOLD (80 bars) / Condition exit", color: "#ff3e3e" },
            { time: "T+?", event: "P&L RECORDED", detail: "GBP→USD conversion, DD state updated, journal logged, Telegram sent", color: "#00e87b" },
          ].map(({ time, event, detail, color }, i) => (
            <div key={i} className="flex items-start gap-4 mb-4 pl-4 arch-fade-in" style={{ animationDelay: `${i * 0.15}s` }}>
              <div className="relative z-10 w-3 h-3 rounded-full mt-1 flex-shrink-0" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono px-1.5 py-0.5" style={{ background: "var(--color-surface-2)", color: "var(--color-text-muted)" }}>{time}</span>
                  <span className="text-xs font-bold" style={{ color }}>{event}</span>
                </div>
                <div className="text-xs mt-0.5" style={{ color: "#8b949e" }}>{detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Fill model rules */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          FILL MODEL — EXIT PRIORITY ORDER (BACKTEST + LIVE)
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {[
            { priority: "1", rule: "GAP-THROUGH SL", desc: "Bar opens past SL → instant fill at open price. Worst case.", color: "#ff3e3e" },
            { priority: "2", rule: "TP TOUCH", desc: "Bar high/low touches TP → fill at TP exactly. OANDA limit order.", color: "#00e87b" },
            { priority: "3", rule: "SL TOUCH", desc: "Bar high/low touches SL → fill at SL + slippage.", color: "#ff8c00" },
          ].map(({ priority, rule, desc, color }) => (
            <div key={priority} className="p-4 flex items-start gap-3" style={{ background: "#080a0f", border: `1px solid ${color}30` }}>
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0"
                style={{ background: `${color}15`, border: `2px solid ${color}`, color }}>
                {priority}
              </div>
              <div>
                <div className="text-xs font-bold" style={{ color }}>{rule}</div>
                <div className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 p-2 text-center text-xs" style={{ background: "#ff3e3e10", border: "1px solid #ff3e3e30", color: "#ff3e3e" }}>
          NO TRAILING STOPS — prevents phantom fills. SL moves only once (break-even).
        </div>
      </div>
    </div>
  );
}

// ─── TAB: RISK ────────────────────────────────────────────────────────────────

function RiskTab() {
  return (
    <div className="space-y-6">
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          TIERED RISK — PER-STRATEGY ALLOCATION
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { strategy: "Alpha-Sweep", risk: 4.0, maxUnitsGold: 100, maxUnitsOil: 5000, color: "#4fc3f7" },
            { strategy: "Mean-Rev", risk: 3.0, maxUnitsGold: 100, maxUnitsOil: 0, color: "#00e87b" },
            { strategy: "Cross-Market", risk: 2.0, maxUnitsGold: 100, maxUnitsOil: 0, color: "#ffd54f" },
          ].map(({ strategy, risk, maxUnitsGold, maxUnitsOil, color }) => (
            <div key={strategy} className="p-5" style={{ background: "#080a0f", border: `1.5px solid ${color}` }}>
              <div className="text-center mb-3">
                <div className="text-sm font-bold" style={{ color }}>{strategy}</div>
                <div className="text-2xl font-bold mt-2" style={{ color }}>{risk}%</div>
                <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>of equity per trade</div>
              </div>
              <MetricBar label="Gold (oz)" value={maxUnitsGold} max={100} color={color} />
              {maxUnitsOil > 0 && <MetricBar label="Oil (barrels)" value={maxUnitsOil} max={5000} color={color} />}
            </div>
          ))}
        </div>
      </div>

      {/* DD Protection State Machine */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          DRAWDOWN PROTECTION — STATE MACHINE
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { state: "NORMAL", condition: "< 3 losses", action: "Full size (1.0×)", color: "#00e87b" },
            { state: "HALVED", condition: "≥ 3 consecutive losses", action: "Half size (0.5×)", color: "#e8c300" },
            { state: "QUARTERED", condition: "Halved + equity < MA", action: "Quarter size (0.25×)", color: "#ff8c00" },
            { state: "PAUSED", condition: "≥ 5 consecutive losses", action: "Skip next 2 signals", color: "#ff3e3e" },
          ].map(({ state, condition, action, color }) => (
            <div key={state} className="p-4 text-center" style={{ background: `${color}08`, border: `1.5px solid ${color}` }}>
              <div className="text-sm font-bold" style={{ color }}>{state}</div>
              <div className="text-xs mt-2" style={{ color: "var(--color-text-muted)" }}>{condition}</div>
              <div className="text-xs mt-1 font-mono" style={{ color }}>{action}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="p-3 text-xs" style={{ background: "#080a0f", border: "1px solid #1a1f27" }}>
            <span className="font-bold" style={{ color: "#00e87b" }}>WIN resets</span>
            <span style={{ color: "var(--color-text-muted)" }}> — any profit trade → consecutive_losses = 0</span>
          </div>
          <div className="p-3 text-xs" style={{ background: "#080a0f", border: "1px solid #1a1f27" }}>
            <span className="font-bold" style={{ color: "#e8c300" }}>Gold + Oil independent</span>
            <span style={{ color: "var(--color-text-muted)" }}> — separate DD state (id=1 vs id=2)</span>
          </div>
        </div>
      </div>

      {/* Position guards */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          POSITION GUARDS — PREVENTING OVEREXPOSURE
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            { guard: "Alpha-Sweep", rule: "Max 3 per day per instrument", color: "#4fc3f7" },
            { guard: "Mean-Rev", rule: "Max 1 open at a time", color: "#00e87b" },
            { guard: "Cross-Market", rule: "Max 1 open + 2-day gap", color: "#ffd54f" },
            { guard: "Max Hold", rule: "Alpha: 80 bars (~4hrs), Cross: 20 days", color: "#ff3e3e" },
          ].map(({ guard, rule, color }) => (
            <div key={guard} className="p-3 text-center" style={{ background: "#080a0f", border: `1px solid ${color}30` }}>
              <div className="text-xs font-bold" style={{ color }}>{guard}</div>
              <div className="text-xs mt-1" style={{ color: "var(--color-text-muted)" }}>{rule}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── TAB: DATA ────────────────────────────────────────────────────────────────

function DataTab() {
  return (
    <div className="space-y-6">
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          OANDA API CALLS — WHAT, WHEN, WHY
        </div>
        <div className="space-y-3 overflow-x-auto">
          {[
            { when: "Every 3 min (London)", call: "get_candles(H1, 12)", returns: "12 hourly bars", purpose: "Asia range calculation", color: "#4fc3f7" },
            { when: "Every 3 min (London)", call: "get_candles(M3, 50)", returns: "50 three-min bars", purpose: "Engulfing detection", color: "#4fc3f7" },
            { when: "Every 3 min (London)", call: "get_candles(D, 2)", returns: "Yesterday + today", purpose: "Daily bias filter", color: "#4fc3f7" },
            { when: "22:00 UTC daily", call: "get_candles(D, 55)", returns: "55 daily bars", purpose: "50-day MA gate", color: "#ffd54f" },
            { when: "Continuous (stream)", call: "Streaming API", returns: "Tick-by-tick bid/ask", purpose: "Break-even detection", color: "#00e87b" },
            { when: "Every 1 min", call: "get_current_price()", returns: "Current bid/ask/mid", purpose: "BE fallback + monitor", color: "var(--color-text-muted)" },
            { when: "On signal", call: "get_account_summary()", returns: "NAV, balance, GBP/USD", purpose: "Position sizing", color: "#e8c300" },
            { when: "On signal", call: "place_market_order()", returns: "Fill price, trade_id", purpose: "Order execution", color: "#00e87b" },
          ].map(({ when, call, returns, purpose, color }, i) => (
            <div key={i} className="flex items-center gap-4 p-3 min-w-[600px]" style={{ background: "#080a0f", border: "1px solid #1a1f27" }}>
              <div className="w-40 flex-shrink-0 text-xs" style={{ color: "var(--color-text-muted)" }}>{when}</div>
              <div className="w-48 flex-shrink-0 text-xs font-mono" style={{ color }}>{call}</div>
              <div className="w-40 flex-shrink-0 text-xs" style={{ color: "var(--color-text-muted)" }}>{returns}</div>
              <div className="text-xs" style={{ color: "#8b949e" }}>{purpose}</div>
            </div>
          ))}
        </div>
      </div>

      {/* DB Tables */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          POSTGRESQL STORAGE — WHAT'S PERSISTED
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {[
            { table: "gd_trades", desc: "Every live trade", fields: ["trade_ref", "strategy", "side", "entry/exit_price", "sl/tp", "pnl_gbp/usd", "exit_reason", "oanda_trade_id"], color: "#00e87b" },
            { table: "gd_signals", desc: "Every signal (taken + skipped)", fields: ["strategy", "direction", "entry/sl/tp", "taken", "skip_reason", "trade_ref"], color: "#4da6ff" },
            { table: "gd_journal", desc: "Event log (JSONB context)", fields: ["trade_ref", "event_type", "price", "context"], color: "#e8c300" },
            { table: "gd_dd_state", desc: "DD protection state", fields: ["consecutive_losses", "pause_counter", "equity", "peak_equity"], color: "#ff3e3e" },
          ].map(({ table, desc, fields, color }) => (
            <div key={table} className="p-4" style={{ background: "#080a0f", border: `1px solid ${color}30` }}>
              <div className="flex items-center gap-2 mb-2">
                <Database className="w-3 h-3" style={{ color }} />
                <span className="text-xs font-bold" style={{ color }}>{table}</span>
                <span className="text-xs ml-auto" style={{ color: "#8b95a5" }}>{desc}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {fields.map(f => (
                  <span key={f} className="px-1.5 py-0.5 text-xs font-mono" style={{ background: "var(--color-surface-2)", color: "var(--color-text-muted)" }}>{f}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 p-2 text-center text-xs" style={{ background: "#e8c30010", border: "1px solid #e8c30030", color: "#e8c300" }}>
          No market data stored locally. All candles fetched from OANDA API on demand.
        </div>
      </div>
    </div>
  );
}

// ─── TAB: SCHEDULE ────────────────────────────────────────────────────────────

function ScheduleTab() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();

  return (
    <div className="space-y-6">
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          24-HOUR TRADING SCHEDULE (UTC)
        </div>

        {/* Timeline visualization */}
        <div className="relative h-16 mb-6 overflow-x-auto" style={{ background: "#080a0f", border: "1px solid #1a1f27" }}>
          {/* Hour markers */}
          {Array.from({ length: 25 }).map((_, h) => (
            <div key={h} className="absolute top-0 bottom-0" style={{ left: `${(h / 24) * 100}%`, borderLeft: "1px solid #1a1f27" }}>
              {h % 4 === 0 && <span className="absolute -bottom-4 text-[8px] -translate-x-1/2" style={{ color: "#8b95a5" }}>{h}:00</span>}
            </div>
          ))}

          {/* London + NY session block */}
          <div className="absolute top-2 h-5 rounded" style={{ left: `${(8 / 24) * 100}%`, width: `${(12 / 24) * 100}%`, background: "#4fc3f730", border: "1px solid #4fc3f7" }}>
            <span className="text-[8px] absolute inset-0 flex items-center justify-center font-bold" style={{ color: "#4fc3f7" }}>ALPHA-SWEEP</span>
          </div>

          {/* Daily scan block */}
          <div className="absolute top-2 h-5 rounded" style={{ left: `${(22 / 24) * 100}%`, width: `${(0.2 / 24) * 100}%`, background: "#ffd54f30", border: "1px solid #ffd54f" }}>
          </div>

          {/* Position monitor (full bar) */}
          <div className="absolute bottom-2 h-3 rounded" style={{ left: "0%", width: "100%", background: "#00e87b10", border: "1px solid #00e87b30" }}>
            <span className="text-[7px] absolute inset-0 flex items-center justify-center" style={{ color: "#00e87b" }}>POSITION MONITOR (every 1 min)</span>
          </div>

          {/* Current time indicator */}
          <div className="absolute top-0 bottom-0 w-[2px]" style={{ left: `${((utcH + utcM / 60) / 24) * 100}%`, background: "#ff3e3e", boxShadow: "0 0 4px #ff3e3e" }} />
        </div>

        {/* Schedule details */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            {
              name: "ALPHA-SWEEP", time: "08:00-20:00 UTC", interval: "Every 3 min",
              detail: "Polls H1 + M3 + Daily for sweep + engulfing pattern. Gold + Oil independently. Up to 3 trades/day.",
              color: "#4fc3f7", istTime: "01:30 PM-01:30 AM IST",
            },
            {
              name: "DAILY SCAN", time: "22:00 UTC", interval: "Once",
              detail: "Cross-Market consensus (6 instruments) + Mean-Rev dip check. Gold only.",
              color: "#ffd54f", istTime: "03:30 AM IST",
            },
            {
              name: "POSITION MONITOR", time: "24/7", interval: "Every 1 min",
              detail: "Checks OANDA for closed trades. Detects SL/TP fills. Enforces max hold.",
              color: "#00e87b", istTime: "Always",
            },
          ].map(({ name, time, interval, detail, color, istTime }) => (
            <div key={name} className="p-4" style={{ background: "#080a0f", border: `1.5px solid ${color}` }}>
              <div className="text-xs font-bold" style={{ color }}>{name}</div>
              <div className="text-xs mt-2 font-mono" style={{ color: "var(--color-text-muted)" }}>{time} ({interval})</div>
              <div className="text-xs mt-1" style={{ color: "#8b949e" }}>{detail}</div>
              <div className="text-xs mt-2 font-mono" style={{ color: "#8b95a5" }}>{istTime}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Current status */}
      <div className="p-3 sm:p-6 rounded-lg" style={{ background: "var(--color-surface-1)", border: "1px solid var(--color-border)" }}>
        <div className="text-[11px] uppercase font-semibold tracking-[0.8px] mb-4" style={{ color: "var(--color-brass-hi)" }}>
          NOTIFICATION EVENTS — TELEGRAM ALERTS
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[
            { event: "SIGNAL TAKEN", emoji: "📈", desc: "Strategy, direction, entry, SL, TP, units" },
            { event: "SIGNAL SKIPPED", emoji: "⏭️", desc: "Strategy, direction, skip reason" },
            { event: "TRADE FILLED", emoji: "✅", desc: "Trade ref, fill price, SL, TP" },
            { event: "TRADE CLOSED", emoji: "💰/🔴", desc: "Exit reason, P&L in £ and $" },
            { event: "BREAK-EVEN", emoji: "🛡️", desc: "Trade ref, new SL level" },
            { event: "ERROR", emoji: "⚠️", desc: "Close failures, stream disconnects" },
          ].map(({ event, emoji, desc }) => (
            <div key={event} className="p-3 flex items-center gap-3" style={{ background: "#080a0f", border: "1px solid #1a1f27" }}>
              <span className="text-lg">{emoji}</span>
              <div>
                <div className="text-xs font-bold" style={{ color: "#c8cdd4" }}>{event}</div>
                <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── CSS ANIMATIONS ───────────────────────────────────────────────────────────

const animationStyles = `
  .arch-node { animation: archFadeSlideUp 0.6s ease-out forwards; opacity: 0; transform: translateY(8px); }
  .arch-arrow { animation: archGrow 0.4s ease-out forwards; transform-origin: left; transform: scaleX(0); }
  .arch-arrow-down { animation: archGrowDown 0.4s ease-out forwards; transform-origin: top; transform: scaleY(0); }
  .arch-bar { animation: archBarGrow 1s ease-out forwards; transform-origin: left; transform: scaleX(0); }
  .arch-fade-in { animation: archFadeIn 0.8s ease-out forwards; opacity: 0; }
  .arch-pulse { animation: archPulse 2s ease-in-out infinite; }

  @keyframes archFadeSlideUp { to { opacity: 1; transform: translateY(0); } }
  @keyframes archGrow { to { transform: scaleX(1); } }
  @keyframes archGrowDown { to { transform: scaleY(1); } }
  @keyframes archBarGrow { to { transform: scaleX(1); } }
  @keyframes archFadeIn { to { opacity: 1; } }
  @keyframes archPulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(1.3); } }
`;
