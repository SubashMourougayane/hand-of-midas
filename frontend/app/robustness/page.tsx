"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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

/** Animated counter — counts from 0 to target on first reveal. */
function CountUp({
  to,
  prefix = "",
  suffix = "",
  duration = 1800,
  decimals = 0,
}: {
  to: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  decimals?: number;
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
      {prefix}
      {decimals > 0 ? v.toFixed(decimals) : Math.round(v).toLocaleString()}
      {suffix}
    </span>
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

/* ─────── Big stat block with animated counter ─────── */

const BigStat = ({
  value,
  label,
  hint,
  prefix = "",
  suffix = "",
  decimals = 0,
}: {
  value: number;
  label: string;
  hint?: string;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}) => (
  <div className="bg-[var(--color-bg)] px-6 py-7">
    <div
      className="font-semibold tracking-tight"
      style={{
        color: "var(--color-brass)",
        fontSize: "clamp(34px,4.5vw,46px)",
        lineHeight: 1,
      }}
    >
      <CountUp to={value} prefix={prefix} suffix={suffix} decimals={decimals} />
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

export default function RobustnessPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
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
            <span
              aria-hidden
              className="inline-block h-3.5 w-3.5 rotate-45 bg-[var(--color-brass)] transition-transform duration-500 group-hover:rotate-[225deg]"
              style={{ boxShadow: "0 0 14px rgba(16,185,129,0.45)" }}
            />
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
            <Link href="/deck" className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]">Deck</Link>
            <Link href="/robustness" className="rounded-full bg-[var(--color-surface-1)] px-4 py-2 font-medium text-[var(--color-text)]">Robustness</Link>
            <Link href="/login" className="ml-2 rounded-full border border-[var(--color-brass)]/50 px-5 py-2 font-semibold text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10">Login</Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10">
        {/* ─── 1. COVER ─── */}
        <section className="mx-auto flex min-h-[calc(100vh-3.75rem)] max-w-5xl items-center px-6 py-16">
          <div className="w-full">
            <Reveal>
              <Eyebrow>How we got here</Eyebrow>
            </Reveal>
            <Reveal delay={120} y={32}>
              <Display size="xl" className="mt-4">
                <span style={{
                  background: "linear-gradient(135deg,#10b981 0%,#34d399 38%,#047857 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}>Robustness.</span>
              </Display>
            </Reveal>
            <Reveal delay={220}>
              <Lead className="mt-7 text-[18px] md:text-[20px]">
                A trading system is only as honest as its validation discipline. Here&apos;s every
                hypothesis we tested, every guard we built, every check that runs before any change ships.
              </Lead>
            </Reveal>
            <Reveal delay={340}>
              <div className="mt-12 grid grid-cols-2 gap-px border-y border-[var(--color-border)] bg-[var(--color-border)] sm:grid-cols-4">
                <BigStat value={436} label="Commits" hint="Single-person history" />
                <BigStat value={25} label="Filter sweeps run" hint="4 shipped, 21 stashed" />
                <BigStat value={84} label="Postmortem docs" hint="Bug reports & analyses" />
                <BigStat value={21} label="Years backtested" hint="2006 → 2026, OHLC CSVs" />
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 2. BACKTEST DISCIPLINE ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Backtest discipline</Eyebrow>
              <Display>Every change runs the real engine on real data.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                The backtest engine consumes the same OHLC CSVs the live scanner consumes. Same signal
                generation. Same fill model. Same DD protection. No replay tools, no hand-tuned numbers.
                Reproducible by anyone with the repo in 30 seconds.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-3">
                {[
                  { v: "2.4M", l: "M3 bars", h: "Per system, 21 years" },
                  { v: "113K", l: "H1 bars", h: "OHLC, OANDA-aligned" },
                  { v: "5.6K", l: "Daily bars", h: "Bias source" },
                  { v: "10,479", l: "Backtest trades", h: "Across 4 systems" },
                  { v: "71.6%", l: "Aggregate WR", h: "Across all 21 years" },
                  { v: "< 2%", l: "Max intra-year DD", h: "Equity smoothness" },
                ].map((s, i) => (
                  <Reveal key={s.l} delay={i * 60}>
                    <div className="bg-[var(--color-bg)] p-7">
                      <div className="num text-[26px] font-semibold tracking-tight text-[var(--color-brass)]">
                        {s.v}
                      </div>
                      <div className="mt-2 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                        {s.l}
                      </div>
                      <div className="mt-1 text-[12px] text-[var(--color-text-muted)]">{s.h}</div>
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>

            <Reveal delay={420}>
              <p className="mt-10 max-w-3xl text-[14.5px] leading-relaxed text-[var(--color-text-dim)]">
                Every filter, every config change, every refactor must run the full 21-year backtest
                pre-and-post and demonstrate measurable improvement on real data — not on selective
                slices, not on synthetic replays. If the numbers don&apos;t move, the change doesn&apos;t ship.
              </p>
            </Reveal>
          </div>
        </section>

        {/* ─── 3. FILTER SWEEPS ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Filter sweeps</Eyebrow>
              <Display>25 hypotheses tested. 4 shipped. 21 stashed.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                The default position on every new idea is no. Each filter goes through the same
                pipeline: branch, instrument, run real backtest pre/post on all four systems, decide
                ship or stash based on the cumulative dollar impact across 21 years. No selective
                ship. No retroactive justification.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
                <div className="border-b border-[var(--color-border)] bg-[var(--color-surface-2)]/40 px-6 py-4">
                  <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-brass)]">
                    Shipped filters · cumulative impact
                  </div>
                </div>
                <div className="divide-y divide-[var(--color-border)]/70">
                  {[
                    {
                      name: "Filter #5 · Earlier break-even arming",
                      detail: "BE 50% → 35% on 3 of 4 systems. Triggered after backtest showed asymmetric protection vs reward.",
                      impact: "+$179k",
                    },
                    {
                      name: "Filter #6 · Trailing SL after BE armed",
                      detail: "Oil Macro only. Other 3 systems excluded after sweep showed negative impact. Per-system precision over global ship.",
                      impact: "+$80k",
                    },
                    {
                      name: "Filter #7 · Partial TP at midpoint",
                      detail: "Bank 50% of position at half-target, runner takes full TP/SL. All 4 systems ship. Largest single contributor.",
                      impact: "+$1.26M",
                    },
                    {
                      name: "Gold Micro · 21-22 UTC market close drop",
                      detail: "Inherited bug from Oil Micro config. After fix, +42 trades, PF 4.40 → 4.52.",
                      impact: "+$27k",
                    },
                  ].map((f, i) => (
                    <Reveal key={f.name} delay={i * 80}>
                      <div className="flex flex-wrap items-baseline justify-between gap-6 px-7 py-6">
                        <div className="flex-1 min-w-0">
                          <div
                            className="text-[18px] text-[var(--color-text)]"
                            style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                          >
                            {f.name}
                          </div>
                          <p className="mt-2 text-[13.5px] leading-[1.6] text-[var(--color-text-dim)]">{f.detail}</p>
                        </div>
                        <div className="num text-[24px] font-semibold tracking-tight text-[var(--color-win)]">
                          {f.impact}
                        </div>
                      </div>
                    </Reveal>
                  ))}
                </div>
                <div className="border-t border-[var(--color-border)] bg-[var(--color-surface-2)]/40 px-7 py-5">
                  <div className="flex justify-between text-[14px]">
                    <span className="text-[var(--color-text-dim)]">Cumulative shipped impact (21 years)</span>
                    <span className="num font-semibold text-[var(--color-brass)]">+$1.547M</span>
                  </div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={420}>
              <div className="mt-10 grid grid-cols-1 gap-5 md:grid-cols-2">
                <div className="rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7">
                  <div
                    className="text-[20px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    Stashed: signal-pruning
                  </div>
                  <p className="mt-3 text-[14px] leading-[1.65] text-[var(--color-text-dim)]">
                    Every signal-side filter we tested — first-sweep-of-day, R:R bounds, anti-trend
                    extension, engulfing-of-doji, wick-rejection thresholds, prev-bar pollution
                    cleanup, TP feasibility — failed on real data. Roughly nine disproven mechanisms.
                  </p>
                  <p className="mt-3 text-[13px] leading-[1.6] text-[var(--color-text-muted)]">
                    Conclusion: directional truth is already encoded by sweep + bias. Trying to
                    filter the entry hurts more winners than losers.
                  </p>
                </div>
                <div className="rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7">
                  <div
                    className="text-[20px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    Stashed: bias-source variants
                  </div>
                  <p className="mt-3 text-[14px] leading-[1.65] text-[var(--color-text-dim)]">
                    Tested today&apos;s intraday data instead of yesterday&apos;s daily candle (Asia, pre-session,
                    lookahead). Macro systems lose $116k–$237k per 21 years. Micros marginal. Stashed.
                  </p>
                  <p className="mt-3 text-[13px] leading-[1.6] text-[var(--color-text-muted)]">
                    The yesterday-anchored bias filter remains the most edge-positive choice.
                  </p>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 4. AUDIT FRAMEWORK ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Audit framework</Eyebrow>
              <Display>Bugs are caught pessimistically.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                When a class of bug is found, we don&apos;t just fix the one instance. We treat it as a
                pattern, audit all four backends in parallel, and write up every sibling we find.
                Recent example: a single dedup-guard typo led to a 24-issue silent-fail audit.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-4">
                {[
                  { v: 24, l: "Issues found", h: "Audit framework" },
                  { v: 20, l: "Fixed + shipped", h: "Verified on VPS" },
                  { v: 2, l: "Accepted as-is", h: "Documented decision" },
                  { v: 2, l: "Not-a-bug", h: "Intentional pattern" },
                ].map((s, i) => (
                  <Reveal key={s.l} delay={i * 60}>
                    <div className="bg-[var(--color-bg)] p-7 text-center">
                      <div className="num text-[40px] font-semibold leading-none tracking-tight text-[var(--color-brass)]">
                        <CountUp to={s.v} />
                      </div>
                      <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                        {s.l}
                      </div>
                      <div className="mt-1 text-[11.5px] text-[var(--color-text-muted)]">{s.h}</div>
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>

            <Reveal delay={420}>
              <div className="mt-12 overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-8 md:p-10">
                <div className="text-[11.5px] uppercase tracking-[0.22em] text-[var(--color-brass)]">
                  Per-issue framework
                </div>
                <div className="mt-4 space-y-3 text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]">
                  <p><span className="text-[var(--color-text)]">RCA</span> — read the actual code, confirm whether the claim holds.</p>
                  <p><span className="text-[var(--color-text)]">Cross-check</span> — does the same pattern exist in the other 3 backends?</p>
                  <p><span className="text-[var(--color-text)]">Verdict</span> — REAL · NOT-REAL · PARTIAL · accepted-as-is.</p>
                  <p><span className="text-[var(--color-text)]">Fix</span> — minimal change, ship, verify on VPS.</p>
                  <p><span className="text-[var(--color-text)]">Sign-off</span> — record final state in audit doc with commit reference.</p>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 5. LIVE ↔ BACKTEST PARITY ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Live ↔ backtest parity</Eyebrow>
              <Display>The two paths must agree.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                The live scanner and backtest engine are parallel implementations of the same
                strategy. A drift between them is a strategy bug — and they&apos;ve happened. Every
                drift bug ever caught has a postmortem, a regression test, and a parity-harness check.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2">
                {[
                  {
                    t: "Parity harness",
                    b: "Runs in 25 seconds. Compares signal generation between live scanner and backtest signal generator across all 4 systems. Soft-gate fails build on catastrophic drift.",
                  },
                  {
                    t: "Calibration plan",
                    b: "Live execution drag (slippage, news spreads, downtime, broker rejection) is not in the backtest. Plan: 3-tier dashboard (Theoretical / Live Calibrated / Live Actual). Deferred until clean live data accumulates.",
                  },
                  {
                    t: "Parity-tested filters",
                    b: "Every shipped filter has run against the parity harness with 100% direction agreement and acceptable signal-count delta.",
                  },
                  {
                    t: "Replay harness — proposed",
                    b: "Future work: run live scanner code directly against historical OHLC, mock-broker fills, validate trade-by-trade against backtest. The definitive regression test for execution drift.",
                  },
                ].map((c, i) => (
                  <Reveal key={c.t} delay={120 + i * 80}>
                    <div className="rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7">
                      <div
                        className="text-[20px] text-[var(--color-text)]"
                        style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                      >
                        {c.t}
                      </div>
                      <p className="mt-3 text-[14.5px] leading-[1.65] text-[var(--color-text-dim)]">{c.b}</p>
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 6. DEFENSE IN DEPTH ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>Defense in depth</Eyebrow>
              <Display>Multiple guards. Multiple layers.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                One guard can fail silently for 18 days before it bites. The fix is layered guards
                that catch the same class of failure at different points in the pipeline.
              </Lead>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-2">
                {[
                  { t: "Open-position dedup at scheduler level", b: "Won&apos;t fire a new entry while one is open. Strategy-IN-list filter." },
                  { t: "Open-position dedup at execute_signal level", b: "Defense-in-depth. If scheduler check is bypassed (refactor, edge case), execute_signal still blocks." },
                  { t: "Persistent sweep blacklist (DB-backed)", b: "Once a sweep is consumed (taken or window-expired), DB row prevents re-fire — even after service restart." },
                  { t: "Equity sanity floor ($100)", b: "Refuses to size if account NAV is corrupt or below floor. Protects against bad broker data." },
                  { t: "Position cap (5,000 barrels / 100 oz)", b: "Hard cap on units regardless of equity. Truncates runaway compounding." },
                  { t: "DD circuit breakers (3 / 5 losses)", b: "Halve risk after 3 consecutive losses, pause entirely after 5. The book recovers before it scales." },
                ].map((d, i) => (
                  <Reveal key={d.t} delay={i * 80}>
                    <div className="h-full bg-[var(--color-bg)] p-9">
                      <div
                        className="text-[18px] text-[var(--color-text)]"
                        style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                      >
                        {d.t}
                      </div>
                      <p
                        className="mt-3 text-[14px] leading-[1.65] text-[var(--color-text-dim)]"
                        dangerouslySetInnerHTML={{ __html: d.b }}
                      />
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 7. WHAT WE DON'T CLAIM ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>What we don&apos;t claim</Eyebrow>
              <Display>Honest limits.</Display>
            </Reveal>

            <Reveal delay={120}>
              <div className="mt-12 space-y-8">
                {[
                  {
                    h: "Backtest is theoretical, not real.",
                    b: "The 21-year backtest assumes zero slippage, perfect fills, no service downtime, no broker rejections. Live haircut is typically 30–50%. Honest framing: lead with dollar P&amp;L on $5k base, not multiplicative percentages.",
                  },
                  {
                    h: "Live data is still accumulating.",
                    b: "Live trading commenced June 2026. As of writing, we have weeks of live history, not years. Calibration to live execution drag requires more data.",
                  },
                  {
                    h: "Past regimes don&apos;t guarantee future ones.",
                    b: "The 21-year backtest covers GFC (2009), Covid (2020), Russia/Ukraine (2022), and more. Each regime is a different test. The strategy survived all 21 years — but a 22nd regime can always be different.",
                  },
                  {
                    h: "We&apos;ve had bugs. We&apos;ll have more.",
                    b: "Phantom fill bugs. Dedup typos. Timezone drifts. Orphan cascades. Each has a postmortem. The discipline is to find them pessimistically — not pretend they don&apos;t exist.",
                  },
                ].map((c, i) => (
                  <Reveal key={c.h} delay={120 + i * 80}>
                    <div className="border-l-2 border-[var(--color-brass)]/40 pl-6">
                      <div
                        className="text-[22px] text-[var(--color-text)]"
                        style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                      >
                        {c.h}
                      </div>
                      <p
                        className="mt-3 max-w-2xl text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]"
                        dangerouslySetInnerHTML={{ __html: c.b }}
                      />
                    </div>
                  </Reveal>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── 8. CTA + FOOTER ─── */}
        <section className="border-t border-[var(--color-border)] bg-[#070a10]">
          <div className="mx-auto max-w-3xl px-6 py-28 text-center md:py-32">
            <Reveal>
              <Display>The discipline is the edge.</Display>
            </Reveal>
            <Reveal delay={120}>
              <p className="mx-auto mt-7 max-w-xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
                The strategy is 1.5 parameters wide. The infrastructure is built to be inspected.
                Every number on this site is reproducible from the repo&apos;s CSVs.
              </p>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-12 flex flex-wrap justify-center gap-3">
                <Link
                  href="/report"
                  className="group inline-flex items-center gap-2 rounded-full bg-[var(--color-brass)] px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[#0a0e14] transition hover:translate-y-[-1px]"
                  style={{ boxShadow: "0 10px 32px rgba(16,185,129,0.18)" }}
                >
                  See the numbers
                  <span className="transition-transform duration-300 group-hover:translate-x-1">→</span>
                </Link>
                <Link
                  href="/deck"
                  className="inline-flex items-center gap-2 rounded-full border border-[var(--color-brass)]/35 px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10"
                >
                  Investor deck
                </Link>
              </div>
            </Reveal>
          </div>

          <footer className="border-t border-[var(--color-border)]/70">
            <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-3 px-6 py-6 md:flex-row md:items-center">
              <div className="flex items-center gap-2.5">
                <span aria-hidden className="inline-block h-2 w-2 rotate-45 bg-[var(--color-brass)]" />
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
                <Link href="/deck" className="transition-colors hover:text-[var(--color-text)]">Deck</Link>
                <a href="mailto:subashtrades.in@gmail.com" className="transition-colors hover:text-[var(--color-text)]">Contact</a>
              </div>
            </div>
            <div className="border-t border-[var(--color-border)]/40">
              <p className="mx-auto max-w-6xl px-6 py-3 text-[11.5px] leading-[1.6] text-[var(--color-text-muted)]">
                Backtest results are based on simulated execution against historical OHLC data.
                Past performance does not guarantee future returns. Live trading commenced June 2026.
              </p>
            </div>
          </footer>
        </section>
      </main>
    </div>
  );
}
