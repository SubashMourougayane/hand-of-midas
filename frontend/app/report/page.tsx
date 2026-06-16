"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import bt from "@/lib/data/backtest.json";
import { CountUp } from "@/components/ui/CountUp";
import { EquityCurve } from "@/components/ui/EquityCurve";
import { SpireMark } from "@/components/brand/SpireMark";

type SystemKey = "aggregate" | "gold" | "micro" | "oil" | "oil-micro";
type CurvePoint = { y: number; e: number; yr_pnl?: number };
type YearlyEntry = {
  year: number;
  trades?: number;
  wins?: number;
  pnl: number;
  wr?: number;
  start_fund?: number;
  end_fund?: number;
  return_pct?: number;
};
type SystemBlock = {
  label: string;
  n: number;
  wr: number;
  pf: number | null;
  pnl: number;
  max_dd: number;
  curve: CurvePoint[];
  yearly?: YearlyEntry[] | null;
};
const data = bt as unknown as Record<SystemKey, SystemBlock>;

const SYSTEMS: { key: SystemKey; short: string; tone: string }[] = [
  { key: "aggregate", short: "All Systems", tone: "var(--color-brass)" },
  { key: "gold", short: "Gold Macro", tone: "var(--color-sys-gold)" },
  { key: "micro", short: "Gold Micro", tone: "var(--color-sys-gold-micro)" },
  { key: "oil", short: "Oil Macro", tone: "var(--color-sys-oil)" },
  { key: "oil-micro", short: "Oil Micro", tone: "var(--color-sys-oil-micro)" },
];

const compactMoney = (v: number) => {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${Math.round(abs / 1e3)}k`;
  return `${sign}$${Math.round(abs)}`;
};

function CountedFormatted({
  value,
  format,
  duration = 1200,
}: {
  value: number;
  format: (n: number) => string;
  duration?: number;
}) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const reduced =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }
    const from = fromRef.current;
    const to = value;
    if (from === to) return;
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(from + (to - from) * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return <span>{format(display)}</span>;
}

function Reveal({
  children,
  delay = 0,
  y = 24,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const reduced =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setVisible(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(ref.current);
    const t = setTimeout(() => setVisible(true), 1500);
    return () => {
      io.disconnect();
      clearTimeout(t);
    };
  }, []);
  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translate3d(0,0,0)" : `translate3d(0, ${y}px, 0)`,
        transition: `opacity 800ms cubic-bezier(0.22, 1, 0.36, 1) ${delay}ms, transform 800ms cubic-bezier(0.22, 1, 0.36, 1) ${delay}ms`,
        willChange: "opacity, transform",
      }}
    >
      {children}
    </div>
  );
}

function YearlyBars({ yearly, triggerKey }: { yearly: YearlyEntry[]; triggerKey: string }) {
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    setDrawn(false);
    const t = setTimeout(() => setDrawn(true), 50);
    return () => clearTimeout(t);
  }, [triggerKey]);

  const entries = [...yearly].sort((a, b) => a.year - b.year);
  const max = Math.max(...entries.map((e) => Math.abs(e.pnl)));
  const totalPos = entries.filter((e) => e.pnl >= 0).reduce((s, e) => s + e.pnl, 0);
  const totalNeg = entries.filter((e) => e.pnl < 0).reduce((s, e) => s + e.pnl, 0);

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
            Yearly P&amp;L
          </div>
          <div
            className="mt-1 text-[14px] text-[var(--color-text)]"
            style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
          >
            {entries.length} years of data
          </div>
        </div>
        <div className="flex items-center gap-4 text-[10px] text-[var(--color-text-muted)]">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 bg-[#10b981]" />
            Profit{" "}
            <span className="text-[var(--color-win)]">{compactMoney(totalPos)}</span>
          </span>
          {totalNeg < 0 && (
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 bg-[#7a3a3a]" />
              Loss{" "}
              <span className="text-[var(--color-loss)]">{compactMoney(totalNeg)}</span>
            </span>
          )}
        </div>
      </div>
      <div
        className="grid items-end gap-[3px]"
        style={{
          gridTemplateColumns: `repeat(${entries.length}, 1fr)`,
          height: 140,
        }}
      >
        {entries.map((e, i) => {
          const h = max > 0 ? (Math.abs(e.pnl) / max) * 100 : 0;
          const v = e.pnl;
          return (
            <div
              key={e.year}
              className="group relative flex h-full flex-col items-end justify-end"
            >
              <div
                className="w-full rounded-t-[1px]"
                style={{
                  height: drawn ? `${h}%` : "0%",
                  background:
                    v >= 0
                      ? "linear-gradient(180deg,#34d399 0%,#10b981 50%,#047857 100%)"
                      : "linear-gradient(180deg,#a04444 0%,#7a3a3a 100%)",
                  transitionProperty: "height, opacity",
                  transitionDuration: "900ms",
                  transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
                  transitionDelay: `${i * 30}ms`,
                  opacity: drawn ? 0.92 : 0,
                }}
              />
              <div className="pointer-events-none absolute -top-9 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-[2px] border border-[var(--color-brass)]/40 bg-[var(--color-surface-2)]/95 px-2.5 py-1.5 text-[10px] backdrop-blur group-hover:block">
                <span className="text-[var(--color-text-muted)]">{e.year}</span>{" "}
                <span style={{ color: v >= 0 ? "var(--color-win)" : "var(--color-loss)" }}>
                  {v >= 0 ? "+" : ""}
                  {compactMoney(v)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <div
        className="mt-2.5 grid gap-[3px] text-center text-[9px] text-[var(--color-text-muted)]"
        style={{
          gridTemplateColumns: `repeat(${entries.length}, 1fr)`,
          fontFamily: "var(--font-mono)",
        }}
      >
        {entries.map((e, i) => (
          <div key={e.year}>{i % 3 === 0 ? `’${String(e.year).slice(2)}` : ""}</div>
        ))}
      </div>
    </div>
  );
}

function SystemTabs({
  value,
  onChange,
}: {
  value: SystemKey;
  onChange: (k: SystemKey) => void;
}) {
  const refs = useRef<Map<SystemKey, HTMLButtonElement>>(new Map());
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });
  useEffect(() => {
    const el = refs.current.get(value);
    if (el) setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
  }, [value]);

  return (
    <div
      role="tablist"
      className="relative inline-flex items-center gap-0 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)] p-1"
    >
      <div
        aria-hidden
        className="absolute top-1 bottom-1 rounded-full bg-[var(--color-brass)]"
        style={{
          left: indicator.left,
          width: indicator.width,
          transition:
            "left 360ms cubic-bezier(0.22, 1, 0.36, 1), width 360ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      />
      {SYSTEMS.map((s) => {
        const active = value === s.key;
        return (
          <button
            key={s.key}
            ref={(el) => {
              if (el) refs.current.set(s.key, el);
            }}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(s.key)}
            className={[
              "relative z-10 px-5 py-2 text-[11.5px] font-medium uppercase tracking-[0.09em] transition-colors duration-300",
              active ? "text-[#0a0e14]" : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
            ].join(" ")}
          >
            {s.short}
          </button>
        );
      })}
    </div>
  );
}

function StatBlock({
  label,
  children,
  tone,
}: {
  label: string;
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <div className="px-6 py-7">
      <div
        className="num font-semibold leading-none tracking-tight"
        style={{
          color: tone || "var(--color-text)",
          fontSize: "clamp(26px,3.2vw,36px)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {children}
      </div>
      <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
        {label}
      </div>
    </div>
  );
}

export default function ReportPage() {
  const [sys, setSys] = useState<SystemKey>("aggregate");
  const block = data[sys];
  const yearlyBlock: SystemBlock = sys === "aggregate" ? data["oil-micro"] : block;
  const yearly: YearlyEntry[] = yearlyBlock.yearly || [];

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* Background */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background: "radial-gradient(900px circle at 50% -10%, rgba(16,185,129,0.05), transparent 60%)",
        }}
      />

      {/* Top Nav */}
      <header
        className="sticky top-0 z-50 backdrop-blur-md"
        style={{
          background: "color-mix(in srgb, var(--color-bg) 94%, transparent)",
          borderBottom: "1px solid color-mix(in srgb, var(--color-border) 100%, transparent)",
        }}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <Link href="/" className="group flex items-center gap-3">
            <SpireMark size={22} className="transition-transform duration-500 group-hover:rotate-[20deg]" />
            <span
              className="text-[19px] italic tracking-tight"
              style={{ fontFamily: "var(--font-display), serif" }}
            >
              Hand of Midas
            </span>
          </Link>
          <nav className="flex items-center gap-2 text-[14px]">
            <Link
              href="/playbook"
              className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]"
            >
              Strategy
            </Link>
            <Link
              href="/report"
              className="rounded-full bg-[var(--color-surface-1)] px-4 py-2 font-medium text-[var(--color-text)]"
            >
              Performance
            </Link>
            <Link
              href="/deck"
              className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]"
            >
              Deck
            </Link>
            <Link
              href="/robustness"
              className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]"
            >
              Robustness
            </Link>
            <Link
              href="/journey"
              className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]"
            >
              Journey
            </Link>
            <Link
              href="/login"
              className="ml-2 rounded-full border border-[var(--color-brass)]/50 px-5 py-2 font-semibold text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10"
            >
              Login
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-6xl px-6 py-16 md:py-20">
        {/* Page header */}
        <Reveal>
          <div className="mb-3 text-[10px] uppercase tracking-[0.22em] text-[var(--color-brass)]">
            Performance Report · 2006–2026
          </div>
          <h1
            style={{
              fontFamily: "var(--font-display), serif",
              fontStyle: "italic",
              fontWeight: 400,
              fontSize: "clamp(40px,6vw,72px)",
              letterSpacing: "-0.025em",
              lineHeight: 1.02,
              textWrap: "balance",
            }}
          >
            Twenty-one years of receipts.
          </h1>
          <p className="mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
            Out-of-sample backtest with production filter management applied. Each
            calendar year begins with a fresh $10,000 capital base. Drawdown
            protection halves position size after three consecutive losses; the
            system pauses after five.
          </p>
        </Reveal>

        {/* Aggregate strip */}
        <Reveal delay={140}>
          <div className="mt-12 grid grid-cols-2 divide-x divide-[var(--color-border)] overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] sm:grid-cols-4">
            <div className="px-6 py-7">
              <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                Realized P&amp;L
              </div>
              <div
                className="num mt-3 font-semibold leading-none tracking-tight"
                style={{
                  color: "var(--color-brass)",
                  fontSize: "clamp(26px,3.2vw,36px)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <CountedFormatted value={4742466} duration={1800} format={compactMoney} />
              </div>
            </div>
            <div className="px-6 py-7">
              <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                Trades
              </div>
              <div
                className="num mt-3 font-semibold leading-none tracking-tight"
                style={{
                  fontSize: "clamp(26px,3.2vw,36px)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <CountUp value={10479} duration={1500} />
              </div>
            </div>
            <div className="px-6 py-7">
              <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                Win Rate
              </div>
              <div
                className="num mt-3 font-semibold leading-none tracking-tight"
                style={{
                  color: "var(--color-win)",
                  fontSize: "clamp(26px,3.2vw,36px)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <CountUp value={71.6} suffix="%" decimals={1} duration={1400} />
              </div>
            </div>
            <div className="px-6 py-7">
              <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                Avg Profit Factor
              </div>
              <div
                className="num mt-3 font-semibold leading-none tracking-tight"
                style={{
                  color: "var(--color-brass)",
                  fontSize: "clamp(26px,3.2vw,36px)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <CountUp value={4.6} suffix="x" decimals={1} duration={1700} />
              </div>
            </div>
          </div>
        </Reveal>

        {/* System tabs */}
        <Reveal delay={220}>
          <div className="mt-14 mb-6">
            <SystemTabs value={sys} onChange={setSys} />
          </div>
        </Reveal>

        {/* Per-system block */}
        <Reveal delay={80}>
          <div className="overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            <div className="grid grid-cols-2 divide-x divide-[var(--color-border)] sm:grid-cols-4">
              <StatBlock label="Total P&L" tone="var(--color-brass)">
                <CountedFormatted value={block.pnl} duration={1100} format={compactMoney} />
              </StatBlock>
              <StatBlock label="Profit Factor">
                {block.pf != null ? (
                  <CountUp value={block.pf} suffix="x" decimals={2} duration={1100} />
                ) : (
                  <span className="text-[var(--color-text-muted)]">—</span>
                )}
              </StatBlock>
              <StatBlock label="Win Rate" tone="var(--color-win)">
                <CountUp value={block.wr} suffix="%" decimals={1} duration={1100} />
              </StatBlock>
              <StatBlock label="Trades">
                <CountUp value={block.n} duration={1100} />
              </StatBlock>
            </div>

            <div className="border-t border-[var(--color-border)]/70 bg-[var(--color-bg)]/40 px-6 py-8 sm:px-10 sm:py-10">
              <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                    Cumulative P&amp;L · {block.label}
                  </div>
                  <div
                    className="mt-1 text-[14px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    21-year out-of-sample track
                  </div>
                </div>
                <div className="text-[10px] text-[var(--color-text-muted)]">
                  Hover to inspect any year
                </div>
              </div>
              {block.curve.length > 0 && (
                <EquityCurve data={block.curve} triggerKey={sys} height={320} />
              )}
            </div>
          </div>
        </Reveal>

        {/* Yearly bars */}
        {yearly.length > 0 && (
          <Reveal delay={120}>
            <div className="mt-6 overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] px-6 py-8 sm:px-10 sm:py-10">
              <YearlyBars yearly={yearly} triggerKey={sys === "aggregate" ? "oil-micro" : sys} />
              {sys === "aggregate" && (
                <p className="mt-4 text-[10px] text-[var(--color-text-muted)]">
                  Yearly bars shown for Oil Micro (largest contributor). Switch tabs above
                  for per-system yearly breakdown.
                </p>
              )}
            </div>
          </Reveal>
        )}

        {/* Per-system table */}
        <Reveal delay={180}>
          <h2
            className="mt-24 mb-7"
            style={{
              fontFamily: "var(--font-display), serif",
              fontStyle: "italic",
              fontWeight: 400,
              fontSize: "clamp(28px,4vw,42px)",
              letterSpacing: "-0.02em",
              lineHeight: 1.05,
              textWrap: "balance",
            }}
          >
            All four systems, side by side.
          </h2>
          <div className="overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead className="border-b border-[var(--color-border)]">
                  <tr className="text-left text-[11.5px] uppercase tracking-[0.16em] text-[var(--color-text-dim)]">
                    <th className="px-6 py-4 font-medium">System</th>
                    <th className="px-6 py-4 text-right font-medium">Trades</th>
                    <th className="px-6 py-4 text-right font-medium">Win Rate</th>
                    <th className="px-6 py-4 text-right font-medium">Profit Factor</th>
                    <th className="px-6 py-4 text-right font-medium">Total P&amp;L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]/50">
                  {SYSTEMS.filter((s) => s.key !== "aggregate").map((s) => {
                    const b = data[s.key];
                    return (
                      <tr
                        key={s.key}
                        className="transition-colors hover:bg-[var(--color-surface-2)]/40"
                      >
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <span
                              aria-hidden
                              className="inline-block h-2 w-2 rounded-full"
                              style={{ background: s.tone }}
                            />
                            <span className="text-[var(--color-text)]">{b.label}</span>
                          </div>
                        </td>
                        <td
                          className="num px-6 py-4 text-right"
                          style={{ fontVariantNumeric: "tabular-nums" }}
                        >
                          {b.n.toLocaleString()}
                        </td>
                        <td
                          className="num px-6 py-4 text-right text-[var(--color-win)]"
                          style={{ fontVariantNumeric: "tabular-nums" }}
                        >
                          {b.wr?.toFixed(1)}%
                        </td>
                        <td
                          className="num px-6 py-4 text-right"
                          style={{ fontVariantNumeric: "tabular-nums" }}
                        >
                          {b.pf?.toFixed(2)}x
                        </td>
                        <td
                          className="num px-6 py-4 text-right font-semibold"
                          style={{
                            color: "var(--color-brass)",
                            fontVariantNumeric: "tabular-nums",
                          }}
                        >
                          {compactMoney(b.pnl)}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="border-t-2 border-[var(--color-brass)]/30 bg-[var(--color-surface-2)]/40">
                    <td className="px-6 py-4 font-semibold text-[var(--color-text)]">
                      Aggregate
                    </td>
                    <td
                      className="num px-6 py-4 text-right font-semibold"
                      style={{ fontVariantNumeric: "tabular-nums" }}
                    >
                      10,479
                    </td>
                    <td
                      className="num px-6 py-4 text-right font-semibold text-[var(--color-win)]"
                      style={{ fontVariantNumeric: "tabular-nums" }}
                    >
                      71.6%
                    </td>
                    <td
                      className="num px-6 py-4 text-right font-semibold"
                      style={{ fontVariantNumeric: "tabular-nums" }}
                    >
                      —
                    </td>
                    <td
                      className="num px-6 py-4 text-right font-semibold"
                      style={{
                        color: "var(--color-brass)",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      $4.74M
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </Reveal>

        {/* Methodology */}
        <Reveal delay={240}>
          <div className="mt-16 grid grid-cols-1 gap-8 md:grid-cols-3 md:gap-6">
            {[
              {
                t: "Methodology",
                b: "All numbers from a tick-aware bar-level fill simulation against H1/M3 historical data from the same broker that handles live execution. Spread, slippage, and broker maintenance halts are modeled.",
              },
              {
                t: "Production filters",
                b: "Five filter modules ship with the live system. Cumulative shipped P&L impact: $1.55M over 21 years, on top of the raw-strategy baseline.",
              },
              {
                t: "Live track record",
                b: "Live trading commenced June 2026 on a JustMarkets MT5 demo. Sample size is small; numbers shown represent the validated backtest distribution that live behavior is sampling from.",
              },
            ].map((c, i) => (
              <Reveal key={c.t} delay={120 + i * 80}>
                <div className="border-l border-[var(--color-brass)]/30 pl-5">
                  <div
                    className="text-[11.5px] font-semibold uppercase tracking-[0.18em] text-[var(--color-brass)]"
                  >
                    {c.t}
                  </div>
                  <p className="mt-3 text-[12.5px] leading-[1.7] text-[var(--color-text-muted)]">
                    {c.b}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </Reveal>

        <Reveal delay={300}>
          <div className="mt-20 flex flex-wrap gap-3">
            <Link
              href="/playbook"
              className="group inline-flex items-center gap-2 rounded-full bg-[var(--color-brass)] px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[#0a0e14] transition hover:translate-y-[-1px]"
              style={{ boxShadow: "0 10px 32px rgba(16,185,129,0.18)" }}
            >
              How the Strategy Works
              <span className="transition-transform duration-300 group-hover:translate-x-1">
                →
              </span>
            </Link>
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[var(--color-text-muted)] transition hover:border-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              ← Back to Home
            </Link>
          </div>
        </Reveal>
      </main>

      <footer className="relative z-10 mt-16 border-t border-[var(--color-border)]">
        <div className="mx-auto max-w-6xl px-6 py-8">
          <p className="text-[10.5px] leading-[1.7] text-[var(--color-text-muted)]">
            Past performance does not guarantee future returns. Backtest figures are
            simulated.
          </p>
        </div>
      </footer>
    </div>
  );
}
