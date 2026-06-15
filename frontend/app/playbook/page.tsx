"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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
  size?: "lg" | "md";
  className?: string;
}) => (
  <h2
    className={className}
    style={{
      fontFamily: "var(--font-display), serif",
      fontStyle: "italic",
      fontWeight: 400,
      fontSize:
        size === "lg" ? "clamp(40px,6vw,72px)" : "clamp(28px,4vw,42px)",
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

const Lead = ({ children }: { children: React.ReactNode }) => (
  <p className="mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
    {children}
  </p>
);

/**
 * Animated SVG diagram — paths stroke in left-to-right when in view.
 * Shows the canonical setup: range box, sweep wick, engulfing candle, entry+TP.
 */
function AnimatedSetupDiagram() {
  const ref = useRef<SVGSVGElement>(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!ref.current) return;
    const reduced =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setProgress(1);
      return;
    }
    let raf = 0;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          io.disconnect();
          const start = performance.now();
          const duration = 2400;
          const tick = (now: number) => {
            const t = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - t, 3);
            setProgress(eased);
            if (t < 1) raf = requestAnimationFrame(tick);
          };
          raf = requestAnimationFrame(tick);
        }
      },
      { threshold: 0.4 }
    );
    io.observe(ref.current);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  // Phase mapping: 0-25% range, 25-50% sweep, 50-65% engulf, 65-100% continuation
  const rangeOpacity = Math.max(0, Math.min(1, progress / 0.2));
  const sweepOpacity = Math.max(0, Math.min(1, (progress - 0.2) / 0.2));
  const engulfOpacity = Math.max(0, Math.min(1, (progress - 0.45) / 0.15));
  const continuationOpacity = Math.max(0, Math.min(1, (progress - 0.6) / 0.3));
  const labelOpacity = Math.max(0, Math.min(1, (progress - 0.85) / 0.15));

  return (
    <svg
      ref={ref}
      viewBox="0 0 800 320"
      className="w-full"
      style={{ maxHeight: 360 }}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <linearGradient id="rangeFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#10b981" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id="sweepGrad" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#ff6b6b" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#ff6b6b" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Range box */}
      <g style={{ opacity: rangeOpacity, transition: "opacity 200ms" }}>
        <rect
          x="60"
          y="130"
          width="260"
          height="80"
          fill="url(#rangeFill)"
          stroke="#10b981"
          strokeOpacity="0.6"
          strokeWidth="0.8"
          strokeDasharray="4,4"
        />
        <line
          x1="60"
          x2="320"
          y1="130"
          y2="130"
          stroke="#10b981"
          strokeOpacity="0.5"
          strokeWidth="0.8"
        />
        <line
          x1="60"
          x2="320"
          y1="210"
          y2="210"
          stroke="#10b981"
          strokeOpacity="0.5"
          strokeWidth="0.8"
        />
        <text
          x="62"
          y="124"
          fontSize="10"
          fill="#10b981"
          fontFamily="var(--font-mono)"
          letterSpacing="0.1em"
        >
          ASIA HIGH
        </text>
        <text
          x="62"
          y="224"
          fontSize="10"
          fill="#10b981"
          fontFamily="var(--font-mono)"
          letterSpacing="0.1em"
        >
          ASIA LOW
        </text>
        <text
          x="190"
          y="178"
          fontSize="13"
          fill="#10b981"
          textAnchor="middle"
          fontStyle="italic"
          fontFamily="var(--font-display),serif"
          opacity={Math.min(1, rangeOpacity * 1.5)}
        >
          Asia range
        </text>
      </g>

      {/* In-range candles (faint) */}
      <g style={{ opacity: rangeOpacity * 0.8 }}>
        <path
          d="M 70 165 L 95 158 L 120 175 L 145 152 L 170 168 L 195 160 L 220 170 L 245 156 L 270 168 L 295 160 L 320 170"
          stroke="#6e7585"
          strokeWidth="1.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>

      {/* Sweep wick — punches above range, closes back below */}
      <g style={{ opacity: sweepOpacity }}>
        <rect
          x="320"
          y="80"
          width="60"
          height="50"
          fill="url(#sweepGrad)"
          stroke="none"
        />
        <path
          d="M 320 170 L 340 158 L 350 110 L 360 165 L 380 175"
          stroke="#ff6b6b"
          strokeWidth="2"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <text
          x="350"
          y="98"
          fontSize="11"
          fill="#ff6b6b"
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          letterSpacing="0.1em"
          opacity={Math.min(1, sweepOpacity * 1.5)}
        >
          SWEEP
        </text>
      </g>

      {/* Engulfing candle */}
      <g style={{ opacity: engulfOpacity }}>
        <rect x="380" y="160" width="18" height="46" fill="#ff6b6b" opacity="0.9" />
        <line x1="389" y1="155" x2="389" y2="210" stroke="#ff6b6b" strokeWidth="1.2" />
        <text
          x="404"
          y="175"
          fontSize="11"
          fill="#ff6b6b"
          fontFamily="var(--font-mono)"
          letterSpacing="0.08em"
          opacity={Math.min(1, engulfOpacity * 1.5)}
        >
          ENGULFING
        </text>
      </g>

      {/* Entry line */}
      <g style={{ opacity: engulfOpacity }}>
        <line
          x1="398"
          y1="206"
          x2="780"
          y2="206"
          stroke="#10b981"
          strokeWidth="1"
          strokeDasharray="3,4"
          opacity="0.7"
        />
        <text
          x="780"
          y="200"
          fontSize="10"
          fill="#10b981"
          textAnchor="end"
          fontFamily="var(--font-mono)"
          letterSpacing="0.12em"
        >
          ENTRY
        </text>
      </g>

      {/* Continuation down */}
      <g style={{ opacity: continuationOpacity }}>
        <path
          d="M 398 206 L 430 218 L 460 230 L 495 222 L 525 245 L 560 240 L 595 256 L 630 250 L 665 268 L 700 264"
          stroke="#25d97a"
          strokeWidth="2.25"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={continuationOpacity * 600}
          strokeDashoffset={(1 - continuationOpacity) * 600}
        />
      </g>

      {/* TP zone */}
      <g style={{ opacity: continuationOpacity }}>
        <line
          x1="60"
          y1="278"
          x2="780"
          y2="278"
          stroke="#25d97a"
          strokeWidth="1"
          strokeDasharray="3,5"
          opacity="0.7"
        />
        <text
          x="780"
          y="294"
          fontSize="10"
          fill="#25d97a"
          textAnchor="end"
          fontFamily="var(--font-mono)"
          letterSpacing="0.12em"
        >
          TARGET
        </text>
      </g>

      {/* Time axis hint */}
      <g style={{ opacity: labelOpacity }}>
        <line x1="60" y1="305" x2="780" y2="305" stroke="#252a35" strokeWidth="0.5" />
        <text
          x="180"
          y="318"
          fontSize="9"
          fill="#6e7585"
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          letterSpacing="0.12em"
        >
          ASIA SESSION
        </text>
        <text
          x="500"
          y="318"
          fontSize="9"
          fill="#6e7585"
          textAnchor="middle"
          fontFamily="var(--font-mono)"
          letterSpacing="0.12em"
        >
          LONDON / NY OVERLAP
        </text>
      </g>
    </svg>
  );
}

const Stage = ({
  num,
  title,
  body,
}: {
  num: string;
  title: string;
  body: string;
}) => (
  <div className="relative pl-8">
    <span
      aria-hidden
      className="absolute left-0 top-1.5 inline-block h-2 w-2 rounded-full bg-[var(--color-brass)]"
      style={{ boxShadow: "0 0 12px rgba(16,185,129,0.5)" }}
    />
    <div className="absolute left-[3.5px] top-5 bottom-0 w-px bg-gradient-to-b from-[var(--color-brass)]/40 to-transparent" />
    <div className="text-[12px] font-semibold uppercase tracking-[0.2em] text-[var(--color-brass)]">
      {num}
    </div>
    <div
      className="mt-2 text-[22px] text-[var(--color-text)]"
      style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
    >
      {title}
    </div>
    <p className="mt-3 max-w-prose pb-2 text-[13.5px] leading-[1.7] text-[var(--color-text-muted)]">
      {body}
    </p>
  </div>
);

export default function PlaybookPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* Background */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          background:
            "radial-gradient(900px circle at 50% -10%, rgba(16,185,129,0.05), transparent 60%)",
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
            <Link
              href="/playbook"
              className="rounded-full bg-[var(--color-surface-1)] px-4 py-2 font-medium text-[var(--color-text)]"
            >
              Strategy
            </Link>
            <Link
              href="/report"
              className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]"
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
              href="/login"
              className="ml-2 rounded-full border border-[var(--color-brass)]/50 px-5 py-2 font-semibold text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10"
            >
              Login
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-5xl px-6 py-16 md:py-20">
        <Reveal>
          <Eyebrow>Strategy Playbook</Eyebrow>
          <Display size="lg">A liquidity sweep, then a fade.</Display>
          <Lead>
            One thesis underpins all four engines. Asia-session price action forms a
            tight range while Western markets sleep. When London opens, that range&apos;s
            extremes get tested — often violently. We trade the failed test, not the
            breakout.
          </Lead>
        </Reveal>

        {/* The Setup */}
        <section className="mt-24 md:mt-28">
          <Reveal>
            <Eyebrow>The Setup</Eyebrow>
            <Display size="md">Three confirmations. One entry.</Display>
          </Reveal>

          <Reveal delay={140}>
            <div className="mt-10 overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-8 md:p-10">
              <AnimatedSetupDiagram />
            </div>
          </Reveal>

          <div className="mt-12 grid grid-cols-1 gap-10 md:grid-cols-3 md:gap-8">
            {[
              {
                num: "01",
                title: "The range",
                body: "Asia hours form a high and a low. We measure the box during the overnight window when liquidity is thin and conviction is low.",
              },
              {
                num: "02",
                title: "The sweep",
                body: "Price punches through one extreme — running stops resting just above or below the range — then closes back inside. A failed breakout is the tell.",
              },
              {
                num: "03",
                title: "The engulfing",
                body: "A three-minute candle in the reversal direction whose body engulfs the prior bar. Now we have alignment: range + sweep + reversal candle.",
              },
            ].map((s, i) => (
              <Reveal key={s.num} delay={180 + i * 100}>
                <Stage {...s} />
              </Reveal>
            ))}
          </div>
        </section>

        {/* Risk frame */}
        <section className="mt-28 md:mt-32">
          <Reveal>
            <Eyebrow>Risk Frame</Eyebrow>
            <Display size="md">Small loss. Banked half. Trail the runner.</Display>
            <Lead>
              The hardest part of trend-following isn&apos;t finding the trade. It&apos;s
              holding it. Five filter modules in production make sure we lock in early
              profit and let the winning side breathe.
            </Lead>
          </Reveal>

          <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-2">
            {[
              {
                title: "Fixed stop, anchored to structure",
                body: "Stop loss sits a few points beyond the sweep wick — the level the market just rejected. If it gets retested, the thesis is invalid and we exit small.",
              },
              {
                title: "Break-even at 35% to target",
                body: "Once price moves 35% of the way to take-profit, the stop slides to entry. The trade becomes free.",
              },
              {
                title: "Half off at 50% to target",
                body: "At halfway, half the position closes for a guaranteed gain. The runner stays alive on a free trade.",
              },
              {
                title: "Trailing exit on Oil Macro",
                body: "After break-even arms, Oil Macro&apos;s runner trails behind the structure. Slow to react, fast to lock. Other systems trade choppier; trailing kills more good trades than it saves.",
              },
              {
                title: "Drawdown halve at three losses",
                body: "Three consecutive stops cuts position size in half. Five pauses the system entirely. Books recover before they scale back up.",
              },
              {
                title: "Per-bar deterministic slippage",
                body: "Backtest fill model is bit-identical between runs. What you see in the historical equity curve is what live trading samples from.",
              },
            ].map((c, i) => (
              <Reveal key={c.title} delay={140 + i * 70}>
                <div className="h-full bg-[var(--color-bg)] p-8 transition-colors duration-500 hover:bg-[var(--color-surface-1)] md:p-9">
                  <div
                    className="text-[19px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    {c.title}
                  </div>
                  <p
                    className="mt-3 text-[13px] leading-[1.7] text-[var(--color-text-muted)]"
                    dangerouslySetInnerHTML={{ __html: c.body }}
                  />
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* Why four */}
        <section className="mt-28 md:mt-32">
          <Reveal>
            <Eyebrow>Why Four Engines</Eyebrow>
            <Display size="md">One thesis. Four expressions.</Display>
            <Lead>
              The same pattern repeats on different timeframes and in different
              markets. Rather than trade one of them well, we trade all four with the
              same risk frame.
            </Lead>
          </Reveal>

          <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-2">
            {[
              {
                tone: "var(--color-sys-gold)",
                name: "Gold Macro",
                cadence: "Once-daily · NY session",
                body: "The classic. Trades the Asia high/low sweep on Gold during London-NY overlap. One trade attempt per day. Highest-conviction setups.",
              },
              {
                tone: "var(--color-sys-gold-micro)",
                name: "Gold Micro",
                cadence: "Rolling 4-hour windows",
                body: "Same thesis on a faster timebox. Each four-hour consolidation produces its own range, swept and faded as a fresh setup. Multiple trades per day.",
              },
              {
                tone: "var(--color-sys-oil)",
                name: "Oil Macro",
                cadence: "Once-daily · NY session",
                body: "Brent Crude version of Gold Macro. Liquidity profile differs — wider stops, longer hold, trail-after-BE works here where it fails elsewhere.",
              },
              {
                tone: "var(--color-sys-oil-micro)",
                name: "Oil Micro",
                cadence: "Rolling 4-hour windows",
                body: "Brent Crude on the faster timebox. Highest absolute P&L contributor of the four. Roughly 77% win rate at backtest scale.",
              },
            ].map((s, i) => (
              <Reveal key={s.name} delay={140 + i * 80}>
                <div className="h-full bg-[var(--color-bg)] p-8 transition-colors duration-500 hover:bg-[var(--color-surface-1)] md:p-9">
                  <div className="flex items-center gap-3">
                    <span
                      aria-hidden
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ background: s.tone, boxShadow: `0 0 10px ${s.tone}` }}
                    />
                    <span
                      className="text-[19px] text-[var(--color-text)]"
                      style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                    >
                      {s.name}
                    </span>
                  </div>
                  <div className="mt-1.5 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                    {s.cadence}
                  </div>
                  <p className="mt-4 text-[13px] leading-[1.7] text-[var(--color-text-muted)]">
                    {s.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* What we won't do */}
        <section className="mt-28 md:mt-32">
          <Reveal>
            <Eyebrow>The Discipline</Eyebrow>
            <Display size="md">What we won&apos;t do.</Display>
          </Reveal>
          <div className="mt-12 grid grid-cols-1 gap-x-8 gap-y-10 md:grid-cols-2">
            {[
              {
                t: "We don&apos;t curve-fit",
                b: "Every filter that ships passes a 21-year out-of-sample backtest with a positive aggregate. Eight signal-pruning candidates that &lsquo;felt right&rsquo; were rejected by data.",
              },
              {
                t: "We don&apos;t override",
                b: "No human discretion mid-trade. The strategy is fully deterministic. If a setup fires and the gates pass, the trade goes; if they don&apos;t, no manual intervention.",
              },
              {
                t: "We don&apos;t chase sample size",
                b: "Three losses in a row halves the size — without exception. The system is allowed to be wrong; we don&apos;t double down to break a streak.",
              },
              {
                t: "We don&apos;t pretend",
                b: "Backtests model spread, slippage, and broker maintenance halts. Live execution uses the same fill model. No phantom trade can pass our books.",
              },
            ].map((c, i) => (
              <Reveal key={c.t} delay={140 + i * 80}>
                <div className="border-l-2 border-[var(--color-brass)]/40 pl-6">
                  <div
                    className="text-[19px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                    dangerouslySetInnerHTML={{ __html: c.t }}
                  />
                  <p
                    className="mt-3 text-[13.5px] leading-[1.7] text-[var(--color-text-muted)]"
                    dangerouslySetInnerHTML={{ __html: c.b }}
                  />
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section className="mt-28 border-t border-[var(--color-border)] pt-20 md:mt-32">
          <Reveal>
            <Display size="md">The numbers are public.</Display>
            <Lead>
              Twenty-one years of out-of-sample backtest, four systems, ten thousand
              trades, in one report.
            </Lead>
          </Reveal>
          <Reveal delay={120}>
            <div className="mt-10 flex flex-wrap gap-3">
              <Link
                href="/report"
                className="group inline-flex items-center gap-2 rounded-full bg-[var(--color-brass)] px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[#0a0e14] transition hover:translate-y-[-1px]"
                style={{ boxShadow: "0 10px 32px rgba(16,185,129,0.18)" }}
              >
                View Full Performance
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
        </section>
      </main>

      <footer className="relative z-10 mt-20 border-t border-[var(--color-border)]">
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
