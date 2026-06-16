"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { SpireMark } from "@/components/brand/SpireMark";

/* ─────── Reveal helper (matches /deck, /robustness) ─────── */

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
      { threshold: 0.18, rootMargin: "0px 0px -10% 0px" }
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

/* ─────── Display + helpers ─────── */

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
        size === "xl"
          ? "clamp(56px,9vw,112px)"
          : size === "lg"
          ? "clamp(40px,6vw,72px)"
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

const Lead = ({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) => (
  <p
    className={`mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)] ${className}`}
  >
    {children}
  </p>
);

/* ─────── Chapter card with milestone dot ─────── */

function Chapter({
  index,
  total,
  date,
  headline,
  body,
  metric,
  metricLabel,
  isLast,
}: {
  index: number;
  total: number;
  date: string;
  headline: string;
  body: React.ReactNode;
  metric?: string;
  metricLabel?: string;
  isLast?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!ref.current) return;
    const reduced =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setActive(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setActive(true);
      },
      { threshold: 0.25, rootMargin: "0px 0px -15% 0px" }
    );
    io.observe(ref.current);
    return () => io.disconnect();
  }, []);

  // 3-column grid: [date col] [rail col with dot] [content col]
  // Rail line + dot share the same column → guaranteed alignment.
  return (
    <div
      ref={ref}
      className="relative grid grid-cols-[68px_28px_1fr] gap-x-4 md:grid-cols-[140px_28px_1fr] md:gap-x-8"
    >
      {/* COL 1 — index + date, right-aligned */}
      <div className="flex flex-col items-end pt-1">
        <div
          className="num text-[12px] uppercase tracking-[0.22em] text-[var(--color-text-muted)]"
          style={{
            fontVariantNumeric: "tabular-nums",
            transform: active ? "translateX(0)" : "translateX(8px)",
            opacity: active ? 1 : 0.55,
            transition:
              "transform 700ms cubic-bezier(0.22,1,0.36,1), opacity 700ms cubic-bezier(0.22,1,0.36,1)",
          }}
        >
          {String(index).padStart(2, "0")} / {String(total).padStart(2, "0")}
        </div>
        <div
          className="mt-2 text-right text-[12.5px] font-semibold uppercase tracking-[0.18em]"
          style={{
            color: active ? "var(--color-brass)" : "var(--color-text-muted)",
            transform: active ? "translateX(0)" : "translateX(8px)",
            transition:
              "color 600ms cubic-bezier(0.22,1,0.36,1), transform 700ms cubic-bezier(0.22,1,0.36,1) 80ms",
          }}
        >
          {date}
        </div>
      </div>

      {/* COL 2 — rail line (full height) + dot (centered horizontally, anchored near top) */}
      <div className="relative" aria-hidden>
        {/* base rail line, dead-center of column */}
        <div
          className="absolute top-0 bottom-0 left-1/2 w-px -translate-x-1/2"
          style={{ background: "var(--color-border-hi)" }}
        />
        {/* animated brass shimmer travelling down inside the same column */}
        <div className="absolute top-0 bottom-0 left-1/2 w-px -translate-x-1/2 overflow-hidden">
          <div
            className="absolute left-0 right-0"
            style={{
              height: "30%",
              background:
                "linear-gradient(to bottom, transparent 0%, color-mix(in srgb, var(--color-brass) 70%, transparent) 50%, transparent 100%)",
              animation: "journey-rail-shimmer 6s linear infinite",
            }}
          />
        </div>

        {/* DOT — pulsing waves are box-shadow on the dot itself (cannot look "detached") */}
        <div className="absolute left-1/2 top-2 -translate-x-1/2">
          <div
            className="relative h-[14px] w-[14px] rounded-full"
            style={{
              background: active ? "var(--color-brass)" : "var(--color-border-hi)",
              transform: active ? "scale(1)" : "scale(0.7)",
              transition:
                "background 600ms cubic-bezier(0.22,1,0.36,1), transform 700ms cubic-bezier(0.34,1.56,0.64,1)",
              animation: active ? "journey-dot-wave 2.6s ease-out infinite" : "none",
            }}
          />
        </div>
      </div>

      {/* COL 3 — chapter body */}
      <div className={`pb-24 ${isLast ? "" : "md:pb-32"}`}>
        {/* headline with brass underline sweep on activation */}
        <Reveal>
          <div
            className="relative mb-5 inline-block text-[26px] md:text-[30px] text-[var(--color-text)]"
            style={{
              fontFamily: "var(--font-display), serif",
              fontStyle: "italic",
              letterSpacing: "-0.015em",
              lineHeight: 1.15,
            }}
          >
            {headline}
            <span
              aria-hidden
              className="absolute bottom-[-6px] left-0 h-[2px] bg-[var(--color-brass)]"
              style={{
                width: active ? "44px" : "0px",
                transition: "width 900ms cubic-bezier(0.22,1,0.36,1) 200ms",
              }}
            />
          </div>
        </Reveal>
        <Reveal delay={100}>
          <div className="max-w-2xl text-[15.5px] leading-[1.75] text-[var(--color-text-dim)]">
            {body}
          </div>
        </Reveal>
        {metric ? (
          <Reveal delay={180}>
            <div
              className="mt-8 inline-flex items-baseline gap-3 border-l-2 pl-5"
              style={{
                borderColor: active ? "var(--color-brass)" : "var(--color-border-hi)",
                transform: active ? "translateX(0)" : "translateX(-12px)",
                opacity: active ? 1 : 0,
                transition:
                  "transform 800ms cubic-bezier(0.22,1,0.36,1) 320ms, opacity 800ms cubic-bezier(0.22,1,0.36,1) 320ms, border-color 600ms cubic-bezier(0.22,1,0.36,1)",
              }}
            >
              <div
                className="num text-[24px] font-semibold tracking-tight md:text-[28px]"
                style={{
                  color: "var(--color-brass)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {metric}
              </div>
              <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-muted)]">
                {metricLabel}
              </div>
            </div>
          </Reveal>
        ) : null}
      </div>
    </div>
  );
}

/* ─────── Page ─────── */

const CHAPTERS: Array<{
  date: string;
  headline: string;
  body: React.ReactNode;
  metric?: string;
  metricLabel?: string;
}> = [
  {
    date: "May 2026",
    headline: "The question.",
    body: (
      <>
        It started as a simple question: <em>can we trade gold profitably with code?</em>{" "}
        The first attempt was a machine-learning system on Indian index options. It looked
        clever on paper. It couldn&apos;t beat a coin flip in practice. Two weeks in, the
        verdict was clear — the edge wasn&apos;t in the model. It was somewhere else
        entirely.
      </>
    ),
    metric: "<50%",
    metricLabel: "Win rate of v0",
  },
  {
    date: "Mid May",
    headline: "First build. Looked too good.",
    body: (
      <>
        Pivoted to gold. Tested thirty trading rules, picked the one that backtested best,
        and shipped it live the same night. The numbers were spectacular —
        backtest claimed almost nine of every ten trades won. We celebrated for about
        seventy-two hours. Then we looked closer.
      </>
    ),
    metric: "PF 10.85",
    metricLabel: "Backtest (it was a lie)",
  },
  {
    date: "May 22",
    headline: "The reckoning.",
    body: (
      <>
        Three quarters of the trades the backtest claimed to win <strong>could not have
        actually filled</strong> at those prices. The engine was buying at the bottom of a
        bar and selling at the top — a thing no real broker would ever let you do. Every
        result we&apos;d been celebrating was fiction. We threw away two weeks of work
        and rebuilt from scratch with one rule: <em>only count trades the broker actually
        fills.</em>
      </>
    ),
    metric: "76%",
    metricLabel: "Of v1 trades were impossible",
  },
  {
    date: "Late May",
    headline: "The hunt.",
    body: (
      <>
        With honest numbers, most strategies fell apart. One survived: a setup based on the
        small lie markets tell in the morning — sweeping past the previous session&apos;s
        high or low, then reversing. We named it <em>Alpha Sweep</em>. We extended it to
        gold and oil, on two timeframes each. Four engines. One thesis. Twenty-one years
        of data backing it.
      </>
    ),
    metric: "21yr",
    metricLabel: "Out-of-sample window",
  },
  {
    date: "Early June",
    headline: "The gauntlet.",
    body: (
      <>
        Going live taught us things backtests can&apos;t. Timezone bugs that shifted every
        trade three hours. Database fields too short to hold the strategy name, silently
        dropping rows. Phantom fills where the broker said one thing and our system said
        another. Each bug got a name, a postmortem, and a guardrail. Same bug can&apos;t bite
        twice.
      </>
    ),
    metric: "6 → 0",
    metricLabel: "Drift bugs caught and walled off",
  },
  {
    date: "Mid June",
    headline: "The refinery.",
    body: (
      <>
        Stopped adding features. Started adding filters. Each one had to prove itself
        across twenty-one years of data, system by system, before it shipped. Most failed
        and got tossed. Three earned their place: take half-profit early, move stops to
        breakeven sooner, trail the runner. Cumulative effect: well over a million dollars
        of additional simulated profit.
      </>
    ),
    metric: "+$1.5M",
    metricLabel: "Filter alpha · 21yr · $5k base",
  },
  {
    date: "Today",
    headline: "Where we stand.",
    body: (
      <>
        Four engines, all live. A new defense layer just shipped — instead of buying at
        the market and paying for slippage, we now place limit orders at favorable prices
        and accept that some signals won&apos;t fill. Bigger picture: we&apos;ve stopped
        chasing the next idea and started compounding the existing edge. <strong>One
        trade is open as you read this.</strong>
      </>
    ),
    metric: "4",
    metricLabel: "Engines live, JustMarkets MT5",
  },
];

export default function JourneyPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* Page-scoped keyframes for animations */}
      <style jsx global>{`
        /* Dot wave: glow + radiating rings (all on the dot itself via box-shadow). */
        /* Outer rings start at 0px spread and expand to ~24px while fading.       */
        @keyframes journey-dot-wave {
          0% {
            box-shadow:
              0 0 0 0 color-mix(in srgb, var(--color-brass) 65%, transparent),
              0 0 0 0 color-mix(in srgb, var(--color-brass) 35%, transparent),
              0 0 18px color-mix(in srgb, var(--color-brass) 55%, transparent);
          }
          70% {
            box-shadow:
              0 0 0 14px color-mix(in srgb, var(--color-brass) 0%, transparent),
              0 0 0 26px color-mix(in srgb, var(--color-brass) 0%, transparent),
              0 0 18px color-mix(in srgb, var(--color-brass) 55%, transparent);
          }
          100% {
            box-shadow:
              0 0 0 14px color-mix(in srgb, var(--color-brass) 0%, transparent),
              0 0 0 26px color-mix(in srgb, var(--color-brass) 0%, transparent),
              0 0 18px color-mix(in srgb, var(--color-brass) 55%, transparent);
          }
        }
        @keyframes journey-rail-shimmer {
          0% {
            transform: translateY(-30%);
          }
          100% {
            transform: translateY(130%);
          }
        }
        @keyframes journey-float {
          0%, 100% {
            transform: translateY(0);
          }
          50% {
            transform: translateY(-6px);
          }
        }
      `}</style>

      {/* Layered background — matches /deck */}
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
        className="pointer-events-none fixed inset-0 z-0 opacity-[0.10]"
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
          borderBottom:
            "1px solid color-mix(in srgb, var(--color-border) 100%, transparent)",
        }}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <Link href="/" className="group flex items-center gap-3">
            <SpireMark
              size={22}
              className="transition-transform duration-500 group-hover:rotate-[20deg]"
            />
            <span
              className="text-[19px] italic tracking-tight"
              style={{ fontFamily: "var(--font-display), serif" }}
            >
              Hand of Midas
            </span>
          </Link>
          <nav className="hidden items-center gap-2 text-[14px] md:flex">
            <Link
              href="/playbook"
              className="rounded-full px-4 py-2 font-medium text-[var(--color-text-dim)] transition-colors hover:bg-[var(--color-surface-1)] hover:text-[var(--color-text)]"
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
              href="/journey"
              className="rounded-full bg-[var(--color-surface-1)] px-4 py-2 font-medium text-[var(--color-text)]"
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

      <main className="relative z-10">
        {/* ─── COVER ─── */}
        <section className="mx-auto flex min-h-[calc(100vh-3.75rem)] max-w-5xl items-center px-6 py-16">
          <div className="w-full">
            <Reveal>
              <div
                className="mb-6"
                style={{ animation: "journey-float 6s ease-in-out infinite" }}
              >
                <SpireMark size={56} animate aria-label="Hand of Midas" />
              </div>
              <Eyebrow>The Story · 2026</Eyebrow>
            </Reveal>
            <Reveal delay={120} y={32}>
              <Display size="xl" className="mt-4">
                <span
                  style={{
                    background:
                      "linear-gradient(135deg,#10b981 0%,#34d399 38%,#047857 100%)",
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                  }}
                >
                  Forty-two days
                </span>
              </Display>
            </Reveal>
            <Reveal delay={220}>
              <Lead className="mt-7 text-[18px] md:text-[20px]">
                From a question to four live trading engines. Not a straight line — three
                rebuilds, eight bug postmortems, two hundred commits, and one hard lesson
                about what backtests are actually telling you.
              </Lead>
            </Reveal>
            <Reveal delay={340}>
              <div className="mt-12 grid grid-cols-2 gap-px border-y border-[var(--color-border)] bg-[var(--color-border)] sm:grid-cols-4">
                {[
                  { value: "42", label: "Days, start to live", tone: "brass" },
                  { value: "3", label: "Full rebuilds" },
                  { value: "200+", label: "Commits", tone: "brass" },
                  { value: "8", label: "Bug postmortems" },
                ].map((s) => (
                  <div
                    key={s.label}
                    className="bg-[var(--color-bg)] px-6 py-7"
                  >
                    <div
                      className="num font-semibold tracking-tight"
                      style={{
                        color:
                          s.tone === "brass"
                            ? "var(--color-brass)"
                            : "var(--color-text)",
                        fontSize: "clamp(28px,3.6vw,40px)",
                        lineHeight: 1,
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {s.value}
                    </div>
                    <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                      {s.label}
                    </div>
                  </div>
                ))}
              </div>
            </Reveal>
            <Reveal delay={460}>
              <p className="mt-8 max-w-2xl text-[13.5px] leading-relaxed text-[var(--color-text-muted)]">
                Scroll to read.
              </p>
            </Reveal>
          </div>
        </section>

        {/* ─── TIMELINE ─── */}
        <section
          className="border-t border-[var(--color-border)]"
          style={{ background: "#070a10" }}
        >
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>The journey</Eyebrow>
              <Display size="lg">Seven chapters.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead>
                Each one is something the system survived — a wrong turn, a bug, a hard
                pivot. The arc isn&apos;t the result. It&apos;s how we got honest enough
                to trust the result.
              </Lead>
            </Reveal>

            {/* Timeline — rail + dots live inside each Chapter's middle column for guaranteed alignment */}
            <div className="relative mt-20">

              {CHAPTERS.map((c, i) => (
                <Chapter
                  key={c.headline}
                  index={i + 1}
                  total={CHAPTERS.length}
                  date={c.date}
                  headline={c.headline}
                  body={c.body}
                  metric={c.metric}
                  metricLabel={c.metricLabel}
                  isLast={i === CHAPTERS.length - 1}
                />
              ))}
            </div>
          </div>
        </section>

        {/* ─── COMING NEXT ─── */}
        <section className="border-t border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="mx-auto max-w-5xl px-6 py-24 md:py-32">
            <Reveal>
              <Eyebrow>What comes next</Eyebrow>
              <Display>Compounding, not chasing.</Display>
            </Reveal>
            <Reveal delay={120}>
              <Lead className="max-w-3xl">
                The system works. The story for the next 90 days is operational —
                accumulating live trades, calibrating live-vs-backtest drift, and tightening
                the execution layer that now stands between a clean signal and a clean fill.
                The next idea can wait. This one needs to compound.
              </Lead>
            </Reveal>
            <div className="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-3">
              {[
                {
                  t: "Calibration",
                  b: "Once we have thirty clean live trades, we publish a live-vs-backtest dashboard. Theoretical, calibrated, actual — three columns, one truth.",
                },
                {
                  t: "Execution layer",
                  b: "Limit-order entry just shipped. Next: better cancel timing, smarter retry on broker rejects, and a slippage attribution log that decomposes every fill.",
                },
                {
                  t: "More markets, later",
                  b: "Indices and FX are on the shelf. Adding them now would multiply surface area without proving the existing edge. They wait their turn.",
                },
              ].map((c, i) => (
                <Reveal key={c.t} delay={i * 100}>
                  <div className="h-full bg-[var(--color-bg)] p-9 transition-colors duration-500 hover:bg-[var(--color-surface-1)]">
                    <div
                      className="mb-4 text-[22px] text-[var(--color-text)]"
                      style={{
                        fontFamily: "var(--font-display), serif",
                        fontStyle: "italic",
                      }}
                    >
                      {c.t}
                    </div>
                    <p className="text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]">
                      {c.b}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ─── CTA ─── */}
        <section className="border-t border-[var(--color-border)]">
          <div className="mx-auto max-w-4xl px-6 py-24 text-center md:py-32">
            <Reveal>
              <Display size="md">Read the receipts.</Display>
            </Reveal>
            <Reveal delay={120}>
              <p className="mx-auto mt-5 max-w-xl text-[15.5px] leading-[1.7] text-[var(--color-text-dim)]">
                Performance, robustness, and the strategy itself — laid out in plain English with
                the numbers behind every claim.
              </p>
            </Reveal>
            <Reveal delay={240}>
              <div className="mt-10 flex flex-wrap justify-center gap-3">
                <Link
                  href="/playbook"
                  className="rounded-full border border-[var(--color-border-hi)] px-6 py-3 text-[14px] font-medium text-[var(--color-text)] transition hover:border-[var(--color-brass)] hover:text-[var(--color-brass)]"
                >
                  Strategy
                </Link>
                <Link
                  href="/report"
                  className="rounded-full border border-[var(--color-border-hi)] px-6 py-3 text-[14px] font-medium text-[var(--color-text)] transition hover:border-[var(--color-brass)] hover:text-[var(--color-brass)]"
                >
                  Performance
                </Link>
                <Link
                  href="/robustness"
                  className="rounded-full border border-[var(--color-border-hi)] px-6 py-3 text-[14px] font-medium text-[var(--color-text)] transition hover:border-[var(--color-brass)] hover:text-[var(--color-brass)]"
                >
                  Robustness
                </Link>
                <Link
                  href="/deck"
                  className="rounded-full bg-[var(--color-brass)] px-6 py-3 text-[14px] font-semibold text-[#0a0d12] transition hover:opacity-90"
                >
                  Investor Deck
                </Link>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ─── Footer ─── */}
        <footer className="border-t border-[var(--color-border)] bg-[var(--color-bg)]">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-8">
            <div className="flex items-center gap-3">
              <SpireMark size={18} />
              <span className="text-[13px] text-[var(--color-text-dim)]">
                Hand of Midas · 2026
              </span>
            </div>
            <div className="text-[12px] text-[var(--color-text-muted)]">
              Solo-built · Live on JustMarkets MT5 · No promises, just receipts.
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
