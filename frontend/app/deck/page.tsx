"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { SpireMark } from "@/components/brand/SpireMark";

/* ─────── Reveal helpers ─────── */

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

const Display = ({
  children,
  size = "lg",
  className = "",
}: {
  children: React.ReactNode;
  size?: "xl" | "lg" | "md";
  className?: string;
}) => (
  <h2
    className={className}
    style={{
      fontFamily: "var(--font-display), serif",
      fontStyle: "italic",
      fontWeight: 400,
      fontSize:
        size === "xl" ? "clamp(56px,9vw,112px)"
        : size === "lg" ? "clamp(40px,6vw,72px)"
        : "clamp(28px,4vw,42px)",
      letterSpacing: "-0.025em",
      lineHeight: 1.02,
      textWrap: "balance" as React.CSSProperties["textWrap"],
    }}
  >
    {children}
  </h2>
);

const Eyebrow = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
    {children}
  </div>
);

const Lead = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => (
  <p className={`mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)] ${className}`}>
    {children}
  </p>
);

/* ─────── Animated counter (matches /robustness) ─────── */

function CountUp({
  to,
  format,
  duration = 1800,
}: {
  to: number;
  format: (v: number) => string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [v, setV] = useState(0);
  const fired = useRef(false);

  useEffect(() => {
    if (!ref.current) return;
    const reduced =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setV(to);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !fired.current) {
          fired.current = true;
          const start = performance.now();
          const tick = (now: number) => {
            const t = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - t, 3);
            setV(to * eased);
            if (t < 1) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        }
      },
      { threshold: 0.3 }
    );
    io.observe(ref.current);
    return () => io.disconnect();
  }, [to, duration]);

  return (
    <span ref={ref} className="num" style={{ fontVariantNumeric: "tabular-nums" }}>
      {format(v)}
    </span>
  );
}

/* ─────── Stat block ─────── */

const Stat = ({
  value,
  label,
  hint,
  tone = "default",
  animate,
}: {
  value: string;
  label: string;
  hint?: string;
  tone?: "default" | "brass";
  /** When provided, animates from 0 → animate.to and applies animate.format to render. */
  animate?: { to: number; format: (v: number) => string };
}) => (
  <div className="bg-[var(--color-bg)] px-6 py-7">
    <div
      className="num font-semibold tracking-tight"
      style={{
        color: tone === "brass" ? "var(--color-brass)" : "var(--color-text)",
        fontSize: "clamp(28px,3.6vw,40px)",
        lineHeight: 1,
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {animate ? <CountUp to={animate.to} format={animate.format} /> : value}
    </div>
    <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
      {label}
    </div>
    {hint ? (
      <div className="mt-1 text-[11.5px] text-[var(--color-text-muted)]">{hint}</div>
    ) : null}
  </div>
);

/* ─────── Page ─────── */

export default function DeckPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* Layered background */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background:
            "radial-gradient(1200px circle at 50% 0%, rgba(16,185,129,0.04), transparent 60%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0 opacity-[0.12]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(60,51,39,0.5) 1px,transparent 1px),linear-gradient(90deg,rgba(60,51,39,0.5) 1px,transparent 1px)",
          backgroundSize: "84px 84px",
          maskImage:
            "radial-gradient(ellipse at 50% 30%, black 30%, transparent 75%)",
          WebkitMaskImage:
            "radial-gradient(ellipse at 50% 30%, black 30%, transparent 75%)",
        }}
      />

      {/* Top nav */}
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
            <Link href="/playbook" className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]">Strategy</Link>
            <Link href="/report" className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]">Performance</Link>
            <Link href="/deck" className="rounded-full bg-[var(--color-surface-1)] px-4 py-2 font-medium text-[var(--color-text)]">Deck</Link>
            <Link href="/robustness" className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]">Robustness</Link>
            <Link href="/journey" className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]">Journey</Link>
            <Link href="/login" className="ml-2 rounded-full border border-[var(--color-brass)]/50 px-5 py-2 font-semibold text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10">Login</Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10">
        {/* ─── 1. COVER ─── */}
        <section className="mx-auto flex min-h-[calc(100vh-3.75rem)] max-w-5xl items-center px-6 py-16">
          <div className="w-full">
            <Reveal>
              <div className="mb-6">
                <SpireMark size={64} animate aria-label="Hand of Midas" />
              </div>
              <Eyebrow>Investor Deck · 2026</Eyebrow>
            </Reveal>
            <Reveal delay={120} y={32}>
              <Display size="xl" className="mt-4">
                <span style={{
                  background: "linear-gradient(135deg,#10b981 0%,#34d399 38%,#047857 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}>Hand of Midas</span>
              </Display>
            </Reveal>
            <Reveal delay={220}>
              <Lead className="mt-7 text-[18px] md:text-[20px]">
                A quantitative trading system for Gold and Brent Crude.
                Four engines, one thesis, twenty-one years of out-of-sample receipts.
              </Lead>
            </Reveal>
            <Reveal delay={340}>
              <div className="mt-12 grid grid-cols-2 gap-px border-y border-[var(--color-border)] bg-[var(--color-border)] sm:grid-cols-4">
                <Stat
                  value="71.6%"
                  label="Win rate (21 yr)"
                  tone="brass"
                  animate={{ to: 71.6, format: (v) => `${v.toFixed(1)}%` }}
                />
                <Stat
                  value="10,479"
                  label="Trades"
                  animate={{ to: 10479, format: (v) => Math.round(v).toLocaleString() }}
                />
                <Stat
                  value="$226k"
                  label="Avg / yr · $5k base"
                  tone="brass"
                  animate={{ to: 226, format: (v) => `$${Math.round(v)}k` }}
                />
                <Stat
                  value="< 2%"
                  label="Max intra-yr DD"
                  animate={{ to: 1.8, format: (v) => `< ${v.toFixed(1)}%` }}
                />
              </div>
            </Reveal>
            <Reveal delay={460}>
              <p className="mt-8 max-w-2xl text-[13.5px] leading-relaxed text-[var(--color-text-muted)]">
                Live since June 2026 on JustMarkets MT5 demo · Solo-built · 21yr backtest re-runnable
                from CSV by anyone with the repo · No black box. No promises. Just receipts.
              </p>
            </Reveal>
          </div>
        </section>

        {/* ─── 2. THE PROBLEM ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>The problem with retail trading</Eyebrow>
              <Display>Most systems lose by design.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                Backtests overfit. Strategies based on intuition collapse. Position sizing scales
                ego. Slippage and fees compound silently. The five-year survival rate of retail algorithmic
                trading systems is rounding-error close to zero — and the survivors usually got lucky on regime, not skill.
              </Lead>
            </Reveal>
            <div className="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-3">
              {[
                {
                  t: "Curve-fitting",
                  b: "Optimized to history. The first regime change wipes out the alpha. We checked: nine signal-pruning hypotheses tested, all failed when run on real 21yr data.",
                },
                {
                  t: "Hidden execution drag",
                  b: "Backtests assume zero slippage. Live broker spreads widen 3–5× during news. Theoretical PF 5 becomes live PF 2 once friction is honest.",
                },
                {
                  t: "Survivorship bias",
                  b: "The systems you read about are the ones that survived. The ones that died are silent. Honest validation requires testing on every year — including the bad ones.",
                },
              ].map((c, i) => (
                <Reveal key={c.t} delay={i * 100}>
                  <div className="h-full bg-[var(--color-bg)] p-9 transition-colors duration-500 hover:bg-[var(--color-surface-1)]">
                    <div
                      className="mb-4 text-[24px] text-[var(--color-text)]"
                      style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                    >
                      {c.t}
                    </div>
                    <p className="text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]">{c.b}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ─── 3. THE THESIS ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>The thesis</Eyebrow>
              <Display>A liquidity sweep, then a fade.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                Asia hours form a tight range while Western markets sleep. When London opens,
                price often punches through that range&apos;s extremes — to harvest stop orders
                clustered just outside — and then turns. We trade the turn, not the run.
              </Lead>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
                {[
                  { k: "Range Forms", v: "Measure Asia&apos;s session high and low. A consolidation block while the West sleeps." },
                  { k: "Sweep Detected", v: "Price punches through the range to clear stops, then closes back inside. A failed breakout." },
                  { k: "Engulfing Confirms", v: "Three-minute engulfing candle in the reversal direction. Now we have a setup." },
                  { k: "Enter, Manage, Exit", v: "Fixed stop. Half-position banked at half-target. Runner trails toward structure exit." },
                ].map((s, i) => (
                  <Reveal key={s.k} delay={120 + i * 60}>
                    <div className="rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7 transition-colors hover:border-[var(--color-brass)]/40">
                      <div
                        className="text-[20px] text-[var(--color-text)]"
                        style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                      >
                        {s.k}
                      </div>
                      <p
                        className="mt-3 text-[14.5px] leading-[1.65] text-[var(--color-text-dim)]"
                        dangerouslySetInnerHTML={{ __html: s.v }}
                      />
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 4. THE NUMBERS — HONEST FRAMING ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>The numbers · 21 years out-of-sample</Eyebrow>
              <Display>Edge, framed honestly.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                Backtest engine resets capital to $5,000 every January 1 — a yearly stress test, not
                a compounding curve. Below: dollar P&amp;L per system on a fresh $5k base, summed across
                21 years. Live execution drag (slippage, news spreads, broker rejections) typically
                eats <span className="text-[var(--color-text)]">30–50%</span> of theoretical.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
                <div className="grid grid-cols-1 gap-px bg-[var(--color-border)] sm:grid-cols-2">
                  {[
                    { name: "Gold Micro", n: 1916, wr: "74.5%", pf: "4.43", pnlValue: 335, pnlFmt: (v: number) => `$${Math.round(v)}k` },
                    { name: "Oil Micro", n: 4641, wr: "77.2%", pf: "5.73", pnlValue: 3.16, pnlFmt: (v: number) => `$${v.toFixed(2)}M` },
                  ].map((s) => (
                    <div key={s.name} className="bg-[var(--color-bg)] p-6">
                      <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                        {s.name}
                      </div>
                      <div
                        className="num mt-3 text-[28px] font-semibold tracking-tight text-[var(--color-brass)]"
                        style={{ fontVariantNumeric: "tabular-nums" }}
                      >
                        <CountUp to={s.pnlValue} format={s.pnlFmt} />
                      </div>
                      <div className="mt-2 text-[11.5px] text-[var(--color-text-muted)]">
                        {s.n} trades · WR {s.wr} · PF {s.pf}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="border-t border-[var(--color-border)] bg-[var(--color-surface-2)]/40 px-7 py-6">
                  <div className="flex flex-wrap items-baseline justify-between gap-3">
                    <div>
                      <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                        Aggregate · both systems
                      </div>
                      <div className="num mt-2 text-[36px] font-semibold tracking-tight text-[var(--color-brass)]">
                        <CountUp to={3.50} format={(v) => `$${v.toFixed(2)}M`} duration={2200} />
                      </div>
                      <div className="mt-1 text-[12px] text-[var(--color-text-muted)]">
                        6,557 trades · 76.4% win rate · max intra-year drawdown under 2%
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                        Realistic live
                      </div>
                      <div className="num mt-2 text-[28px] font-semibold tracking-tight text-[var(--color-text)]">
                        $1.0M – $1.8M
                      </div>
                      <div className="mt-1 text-[12px] text-[var(--color-text-muted)]">
                        After 30–50% execution-drag haircut
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={360}>
              <p className="mt-8 max-w-3xl text-[13.5px] leading-relaxed text-[var(--color-text-muted)]">
                Methodology and full per-year breakdown:{" "}
                <Link href="/report" className="text-[var(--color-brass)] underline-offset-4 hover:underline">
                  Performance Report →
                </Link>
              </p>
            </Reveal>
          </div>
        </section>

        {/* ─── 5. ARCHITECTURE ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Architecture</Eyebrow>
              <Display>Two engines. Two markets. One timeframe.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                Same fade thesis, two expressions across two markets. The cross-market
                diversification is the risk control — when one engine misses the setup,
                the other catches it.
              </Lead>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
                {[
                  { sys: "Gold Micro", desc: "XAU/USD · rolling 4-hour micro structure · multiple intraday opportunities", color: "#f59e0b" },
                  { sys: "Oil Micro", desc: "BCO/USD · rolling 4-hour micro structure · highest-volume engine", color: "#38bdf8" },
                ].map((e, i) => (
                  <Reveal key={e.sys} delay={120 + i * 60}>
                    <div className="rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7">
                      <div className="flex items-center gap-3">
                        <span
                          aria-hidden
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ background: e.color, boxShadow: `0 0 8px ${e.color}` }}
                        />
                        <div
                          className="text-[20px] text-[var(--color-text)]"
                          style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                        >
                          {e.sys}
                        </div>
                      </div>
                      <p className="mt-3 text-[14.5px] leading-[1.65] text-[var(--color-text-dim)]">
                        {e.desc}
                      </p>
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 6. RISK FRAME ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Risk frame</Eyebrow>
              <Display>What we won&apos;t do.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                Edge dies at the SL. Discipline doesn&apos;t.
              </Lead>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-2">
                {[
                  { t: "Hard stop on every trade", b: "No discretionary holds. Server-side SL with the broker. The market closes our trade if we&apos;re wrong; we don&apos;t pray." },
                  { t: "4% NAV per trade, capped", b: "Position sizing is risk-based, not lot-based. MAX_UNITS hard cap (5,000 barrels Oil / 100 oz Gold) prevents runaway compounding into oversized notional." },
                  { t: "DD circuit breaker", b: "Three consecutive losses halve risk. Five consecutive losses pause the system entirely. The book recovers before it scales." },
                  { t: "No martingale, no averaging-down", b: "One position per system at a time. Lost trades stay lost. No recovery doubling — the most common retail account-killer." },
                  { t: "No black-box ML", b: "The strategy is 1.5 parameters wide and fully auditable. You can run the 21-year backtest from the repo&apos;s CSVs in 30 seconds and verify every trade." },
                  { t: "No promises", b: "Past performance is not future returns. Backtest is theoretical; live haircut is real. Calibration to live data is in progress." },
                ].map((r, i) => (
                  <Reveal key={r.t} delay={120 + i * 80}>
                    <div className="h-full bg-[var(--color-bg)] p-9">
                      <div
                        className="text-[22px] text-[var(--color-text)]"
                        style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                      >
                        {r.t}
                      </div>
                      <p
                        className="mt-3 text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]"
                        dangerouslySetInnerHTML={{ __html: r.b }}
                      />
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 7. STAGE & TEAM ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Stage</Eyebrow>
              <Display>Live since June 2026. Solo-built. Transparent.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                One person, full-stack: strategy research, backtest engine, live broker integration,
                operations, dashboard. No team to dilute conviction, no fund vehicle yet, no opaque
                architecture. Currently running on a JustMarkets MT5 demo account on a dedicated VPS.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-2 gap-px border-y border-[var(--color-border)] bg-[var(--color-border)] sm:grid-cols-4">
                <Stat
                  value="436"
                  label="Commits"
                  hint="Single-person history"
                  animate={{ to: 436, format: (v) => Math.round(v).toLocaleString() }}
                />
                <Stat
                  value="25+"
                  label="Filter sweeps run"
                  hint="4 shipped · 21 stashed"
                  animate={{ to: 25, format: (v) => `${Math.round(v)}+` }}
                />
                <Stat
                  value="24"
                  label="Audit-class bugs caught"
                  hint="Found pessimistically · 20 fixed"
                  animate={{ to: 24, format: (v) => `${Math.round(v)}` }}
                />
                <Stat
                  value="< 2%"
                  label="Max intra-year DD"
                  hint="Across all 21 years"
                  animate={{ to: 1.8, format: (v) => `< ${v.toFixed(1)}%` }}
                />
              </div>
            </Reveal>

            <Reveal delay={360}>
              <p className="mt-10 max-w-3xl text-[14.5px] leading-relaxed text-[var(--color-text-dim)]">
                The infrastructure is built to be inspected. Live state, broker positions, and
                strategy decisions are queryable through a debug API. Every filter that shipped or
                stashed has a documented before/after on real 21-year data — no replay tools, no
                hand-tuned numbers.
              </p>
            </Reveal>

            <Reveal delay={460}>
              <p className="mt-6 max-w-3xl text-[14.5px] leading-relaxed text-[var(--color-text-dim)]">
                Full technical detail:{" "}
                <Link href="/robustness" className="text-[var(--color-brass)] underline-offset-4 hover:underline">
                  Robustness report →
                </Link>
              </p>
            </Reveal>
          </div>
        </section>

        {/* ─── 8. ASK / CONTACT ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-3xl px-6 py-28 text-center md:py-32">
            <Reveal>
              <Display>The numbers are public. The system is live.</Display>
            </Reveal>
            <Reveal delay={120}>
              <p className="mx-auto mt-7 max-w-xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
                Read the playbook. Audit the performance. Inspect the robustness. Reach out if it
                interests you.
              </p>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-12 flex flex-wrap justify-center gap-3">
                <a
                  href="mailto:subashtrades.in@gmail.com?subject=Hand%20of%20Midas%20%E2%80%94%20Investor%20Inquiry"
                  className="group inline-flex items-center gap-2 rounded-full bg-[var(--color-brass)] px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[#0a0e14] transition hover:translate-y-[-1px]"
                  style={{ boxShadow: "0 10px 32px rgba(16,185,129,0.18)" }}
                >
                  Reach out
                  <span className="transition-transform duration-300 group-hover:translate-x-1">→</span>
                </a>
                <Link
                  href="/playbook"
                  className="inline-flex items-center gap-2 rounded-full border border-[var(--color-brass)]/35 px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10"
                >
                  Strategy Playbook
                </Link>
              </div>
            </Reveal>
          </div>

          {/* Footer (matches landing) */}
          <footer className="border-t border-[var(--color-border)]/70">
            <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-3 px-6 py-6 md:flex-row md:items-center">
              <div className="flex items-center gap-2.5">
                <SpireMark size={14} compact />
                <span
                  className="text-[14px] italic text-[var(--color-text-dim)]"
                  style={{ fontFamily: "var(--font-display), serif" }}
                >
                  Hand of Midas — by Subash Mourougayane
                </span>
              </div>
              <div className="flex flex-wrap gap-5 text-[13px] text-[var(--color-text-dim)]">
                <Link href="/playbook" className="transition-colors hover:text-[var(--color-text)]">Playbook</Link>
                <Link href="/report" className="transition-colors hover:text-[var(--color-text)]">Performance</Link>
                <Link href="/robustness" className="transition-colors hover:text-[var(--color-text)]">Robustness</Link>
                <Link href="/journey" className="transition-colors hover:text-[var(--color-text)]">Journey</Link>
                <a href="mailto:subashtrades.in@gmail.com" className="transition-colors hover:text-[var(--color-text)]">Contact</a>
              </div>
            </div>
            <div className="border-t border-[var(--color-border)]/40">
              <p className="mx-auto max-w-6xl px-6 py-3 text-[11.5px] leading-[1.6] text-[var(--color-text-muted)]">
                Backtest results are based on simulated execution against historical OHLC data with modeled spread.
                Past performance does not guarantee future returns. Live trading commenced June 2026.
                Realistic live haircut: 30–50% of theoretical, refined as live data accumulates.
              </p>
            </div>
          </footer>
        </section>
      </main>
    </div>
  );
}
