"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import bt from "@/lib/data/backtest.json";
import { CountUp } from "@/components/ui/CountUp";
import { EquityCurve } from "@/components/ui/EquityCurve";
import { SpireMark } from "@/components/brand/SpireMark";

// Macros retired 2026-06-19. Keys retained for backward-compat with
// data/backtest.json which still has historical Macro stats; runtime
// SYSTEMS list filters them out.
type SystemKey = "aggregate" | "gold" | "micro" | "oil" | "oil-micro";
type CurvePoint = { y: number; e: number; yr_pnl?: number };
type SystemBlock = {
  label: string;
  n: number;
  wr: number;
  pf: number | null;
  pnl: number;
  max_dd: number;
  curve: CurvePoint[];
};
const data = bt as unknown as Record<SystemKey, SystemBlock>;

const SYSTEMS: { key: SystemKey; short: string; tone: string }[] = [
  { key: "aggregate", short: "All Systems", tone: "var(--color-brass)" },
  { key: "micro", short: "Gold Micro", tone: "var(--color-sys-gold-micro)" },
  { key: "oil-micro", short: "Oil Micro", tone: "var(--color-sys-oil-micro)" },
];

const compactMoney = (v: number) => {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${Math.round(abs / 1e3)}k`;
  return `${sign}$${Math.round(abs)}`;
};

/** Tween a number then run a custom formatter over it. */
function CountedFormatted({
  value,
  format,
  duration = 1200,
  className,
}: {
  value: number;
  format: (n: number) => string;
  duration?: number;
  className?: string;
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
  return <span className={className}>{format(display)}</span>;
}

/** Scroll-triggered reveal — fades + slides in on enter. */
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
    // Failsafe: ensure content is visible even if observer never fires
    // (e.g. during a fullPage screenshot capture or below-fold print).
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
    if (el) {
      setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
    }
  }, [value]);

  return (
    <div
      role="tablist"
      className="relative inline-flex items-center gap-0 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)] p-1"
    >
      {/* Animated brass background that slides */}
      <div
        aria-hidden
        className="absolute top-1 bottom-1 rounded-full bg-[var(--color-brass)]"
        style={{
          left: indicator.left,
          width: indicator.width,
          transition: "left 360ms cubic-bezier(0.22, 1, 0.36, 1), width 360ms cubic-bezier(0.22, 1, 0.36, 1)",
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
              "relative z-10 px-4 py-2 text-[11.5px] font-medium uppercase tracking-[0.09em] transition-colors duration-300",
              active
                ? "text-[#0a0e14]"
                : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]",
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
  align = "left",
}: {
  label: string;
  children: React.ReactNode;
  tone?: string;
  align?: "left" | "center";
}) {
  return (
    <div className={align === "center" ? "px-6 py-7 text-center" : "px-6 py-7 text-left"}>
      <div
        className="num text-[clamp(28px,3.6vw,40px)] font-semibold leading-none tracking-tight"
        style={{ color: tone || "var(--color-text)", fontVariantNumeric: "tabular-nums" }}
      >
        {children}
      </div>
      <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
        {label}
      </div>
    </div>
  );
}

const SECTION_IDS = ["hero", "performance", "thesis", "edge", "outro"] as const;
type SectionId = (typeof SECTION_IDS)[number];
const SECTION_LABELS: Record<SectionId, string> = {
  hero: "Hand of Midas",
  performance: "Performance",
  thesis: "The Thesis",
  edge: "Edge",
  outro: "Get Started",
};

export default function LandingPage() {
  const [sys, setSys] = useState<SystemKey>("aggregate");
  const block = data[sys];

  // Subtle parallax on hero scroll
  const [scrollY, setScrollY] = useState(0);
  useEffect(() => {
    const onScroll = () => setScrollY(window.scrollY);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Activate scroll-snap on root only while landing is mounted; cleanup on unmount.
  useEffect(() => {
    document.documentElement.setAttribute("data-snap", "true");
    return () => {
      document.documentElement.removeAttribute("data-snap");
    };
  }, []);

  // Track active section for the right-rail indicator.
  const [active, setActive] = useState<SectionId>("hero");
  useEffect(() => {
    const els = SECTION_IDS.map((id) => document.getElementById(id)).filter(
      Boolean
    ) as HTMLElement[];
    if (els.length === 0) return;
    const io = new IntersectionObserver(
      (entries) => {
        // Pick the most-visible entry currently intersecting.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target?.id) {
          setActive(visible.target.id as SectionId);
        }
      },
      { threshold: [0.4, 0.6, 0.8] }
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* Layered backgrounds */}
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

      {/* ─────── TOP NAV ─────── */}
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
              className="text-[19px] italic tracking-tight text-[var(--color-text)]"
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

      {/* ─────── SECTION RAIL (right edge dots) ─────── */}
      <nav
        aria-label="Page sections"
        className="pointer-events-none fixed right-5 top-1/2 z-40 hidden -translate-y-1/2 md:block"
      >
        <ul className="pointer-events-auto flex flex-col gap-3">
          {SECTION_IDS.map((id) => {
            const isActive = active === id;
            return (
              <li key={id}>
                <a
                  href={`#${id}`}
                  aria-label={SECTION_LABELS[id]}
                  aria-current={isActive ? "true" : undefined}
                  className="group relative flex items-center"
                  onClick={(e) => {
                    e.preventDefault();
                    document
                      .getElementById(id)
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  <span
                    className="absolute right-7 whitespace-nowrap rounded-full bg-[var(--color-surface-1)]/95 px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--color-text-dim)] opacity-0 backdrop-blur transition-opacity duration-200 group-hover:opacity-100"
                    style={{ border: "1px solid var(--color-border)" }}
                  >
                    {SECTION_LABELS[id]}
                  </span>
                  <span
                    className="block transition-all duration-300 ease-out"
                    style={{
                      width: isActive ? 22 : 6,
                      height: 6,
                      borderRadius: 999,
                      background: isActive
                        ? "var(--color-brass)"
                        : "color-mix(in srgb, var(--color-text-muted) 60%, transparent)",
                    }}
                  />
                </a>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* ─────── HERO ─────── */}
      <section
        id="hero"
        className="snap-section relative z-10 flex min-h-[calc(100vh-3.75rem)] items-center"
      >
        <div className="mx-auto w-full max-w-6xl px-6 py-12 text-center">
          <div
            style={{
              transform: `translateY(${scrollY * 0.18}px)`,
              willChange: "transform",
            }}
          >
            <Reveal y={12}>
              <div className="mb-7 inline-flex items-center gap-2.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-1)]/70 px-4 py-1.5 backdrop-blur">
                <span
                  aria-hidden
                  className="relative flex h-1.5 w-1.5"
                >
                  <span className="absolute inset-0 animate-ping rounded-full bg-[var(--color-brass)] opacity-60" />
                  <span className="relative h-1.5 w-1.5 rounded-full bg-[var(--color-brass)]" />
                </span>
                <span className="text-[11px] font-medium uppercase tracking-[0.2em] text-[var(--color-text-dim)]">
                  Quantitative Commodities · Live since June 2026
                </span>
              </div>
            </Reveal>

            <Reveal delay={80} y={20}>
              <div className="mb-6 flex justify-center">
                <SpireMark size={88} animate aria-label="Hand of Midas" />
              </div>
            </Reveal>

            <Reveal delay={120} y={32}>
              <h1
                className="mx-auto max-w-4xl"
                style={{
                  fontFamily: "var(--font-display), serif",
                  fontStyle: "italic",
                  fontWeight: 400,
                  fontSize: "clamp(56px, 9.2vw, 112px)",
                  lineHeight: 0.98,
                  letterSpacing: "-0.03em",
                  background:
                    "linear-gradient(135deg,#10b981 0%,#34d399 38%,#047857 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  textWrap: "balance",
                }}
              >
                Hand of Midas
              </h1>
            </Reveal>

            <Reveal delay={220} y={20}>
              <p className="mx-auto mt-7 max-w-2xl text-[18px] leading-[1.6] text-[var(--color-text-dim)] md:text-[20px]">
                A quantitative trading system for Gold and Brent Crude.
                <br />
                Four engines.{" "}
                <span className="text-[var(--color-text)]">
                  One thesis: Asia consolidation, swept and faded.
                </span>
              </p>
            </Reveal>

            {/* Headline numbers */}
            <Reveal delay={340} y={32}>
              <div className="mx-auto mt-14 grid max-w-3xl grid-cols-1 gap-px border-y border-[var(--color-border)] bg-[var(--color-border)] sm:grid-cols-3">
                <div className="bg-[var(--color-bg)] px-6 py-7">
                  <div
                    className="num font-semibold tracking-tight"
                    style={{
                      color: "var(--color-brass)",
                      fontSize: "clamp(34px,4.5vw,46px)",
                      lineHeight: 1,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    <CountedFormatted
                      value={4742466}
                      duration={2000}
                      format={(v) => `$${(v / 1e6).toFixed(2)}M`}
                    />
                  </div>
                  <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                    21-yr Backtest P&amp;L
                  </div>
                </div>
                <div className="bg-[var(--color-bg)] px-6 py-7">
                  <div
                    className="num font-semibold tracking-tight text-[var(--color-text)]"
                    style={{
                      fontSize: "clamp(34px,4.5vw,46px)",
                      lineHeight: 1,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    <CountUp value={71.6} suffix="%" decimals={1} duration={1600} />
                  </div>
                  <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                    Win Rate · 10,479 Trades
                  </div>
                </div>
                <div className="bg-[var(--color-bg)] px-6 py-7">
                  <div
                    className="num font-semibold tracking-tight"
                    style={{
                      color: "var(--color-brass)",
                      fontSize: "clamp(34px,4.5vw,46px)",
                      lineHeight: 1,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    <CountUp value={4.6} suffix="x" decimals={1} duration={1800} />
                  </div>
                  <div className="mt-3 text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                    Avg Profit Factor
                  </div>
                </div>
              </div>
            </Reveal>

            <Reveal delay={460} y={16}>
              <div className="mt-12 flex flex-wrap items-center justify-center gap-3">
                <Link
                  href="/report"
                  className="group inline-flex items-center gap-2 rounded-full bg-[var(--color-brass)] px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[#0a0e14] transition hover:translate-y-[-1px]"
                  style={{ boxShadow: "0 10px 32px rgba(16,185,129,0.18)" }}
                >
                  View Performance
                  <span className="transition-transform duration-300 group-hover:translate-x-1">
                    →
                  </span>
                </Link>
                <Link
                  href="/playbook"
                  className="inline-flex items-center gap-2 rounded-full border border-[var(--color-brass)]/35 px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10"
                >
                  Read the Playbook
                </Link>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ─────── INTERACTIVE PERFORMANCE ─────── */}
      <section
        id="performance"
        className="snap-section relative z-10 flex min-h-[calc(100vh-3.75rem)] items-center"
      >
        <div className="mx-auto w-full max-w-6xl px-6 py-12">
        <Reveal>
          <div className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
            Per-System Performance
          </div>
          <h2
            className="max-w-3xl"
            style={{
              fontFamily: "var(--font-display), serif",
              fontStyle: "italic",
              fontWeight: 400,
              fontSize: "clamp(32px,4.6vw,52px)",
              letterSpacing: "-0.02em",
              lineHeight: 1.05,
              textWrap: "balance",
            }}
          >
            Four engines. Independently measured.
          </h2>
          <p className="mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
            Two markets — Gold and Brent Crude — each trades on two timeframes: a
            once-daily session sweep and a rolling four-hour micro structure. Same
            thesis, four expressions, twenty-one years of receipts.
          </p>
        </Reveal>

        <Reveal delay={140}>
          <div className="mt-10 flex justify-start">
            <SystemTabs value={sys} onChange={setSys} />
          </div>
        </Reveal>

        <Reveal delay={220}>
          <div className="mt-8 overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)]">
            {/* Stat strip */}
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

            {/* Curve */}
            <div className="border-t border-[var(--color-border)]/70 bg-[var(--color-bg)]/40 px-6 py-7 sm:px-10 sm:py-9">
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <div className="text-[11.5px] uppercase tracking-[0.18em] text-[var(--color-text-dim)]">
                    Cumulative P&amp;L · {block.label}
                  </div>
                  <div
                    className="mt-1 text-[15px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    Across 21 years of out-of-sample data
                  </div>
                </div>
                <div className="text-[11.5px] text-[var(--color-text-dim)]">
                  Hover the curve for any year
                </div>
              </div>
              {block.curve.length > 0 && (
                <EquityCurve data={block.curve} triggerKey={sys} height={240} />
              )}
            </div>
          </div>
        </Reveal>
        </div>
      </section>

      {/* ─────── HOW IT WORKS ─────── */}
      <section
        id="thesis"
        className="snap-section relative z-10 flex min-h-[calc(100vh-3.75rem)] items-center border-t border-[var(--color-border)] bg-[#070a10]"
      >
        <div className="mx-auto w-full max-w-6xl px-6 py-12">
          <Reveal>
            <div className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
              The Thesis
            </div>
            <h2
              className="max-w-3xl"
              style={{
                fontFamily: "var(--font-display), serif",
                fontStyle: "italic",
                fontWeight: 400,
                fontSize: "clamp(32px,4.6vw,52px)",
                letterSpacing: "-0.02em",
                lineHeight: 1.05,
                textWrap: "balance",
              }}
            >
              Liquidity sweeps the asleep, then reverses.
            </h2>
            <p className="mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
              Asia hours form a tight range while Western markets sleep. When London
              opens, price often runs that range&apos;s extremes to harvest stops — and
              then turns. We trade the turn, not the run.
            </p>
          </Reveal>

          <div className="mt-14 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
            {[
              {
                step: "01",
                title: "Range Forms",
                body: "We measure Asia&apos;s session high and low. A rangebound block while the West sleeps.",
              },
              {
                step: "02",
                title: "Sweep Detected",
                body: "Price punches through the range to clear stops, then closes back inside. A failed breakout.",
              },
              {
                step: "03",
                title: "Engulfing Confirms",
                body: "Three-minute engulfing candle in the reversal direction. Now we have a setup.",
              },
              {
                step: "04",
                title: "Enter, Manage, Exit",
                body: "Fixed stop. Half-position banked at half-target. Runner trails toward the structure exit.",
              },
            ].map((s, i) => (
              <Reveal key={s.step} delay={120 + i * 100}>
                <div
                  className="group relative h-full overflow-hidden rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7 transition-all duration-500 hover:border-[var(--color-brass)]/40"
                  style={{
                    transition: "transform 500ms cubic-bezier(0.22,1,0.36,1), border-color 500ms",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.transform = "translateY(-4px)")}
                  onMouseLeave={(e) => (e.currentTarget.style.transform = "translateY(0)")}
                >
                  <div
                    aria-hidden
                    className="absolute inset-x-0 top-0 h-px"
                    style={{
                      background:
                        "linear-gradient(90deg, transparent 0%, var(--color-brass) 50%, transparent 100%)",
                      opacity: 0.5,
                    }}
                  />
                  <div className="text-[12px] font-semibold tracking-[0.2em] text-[var(--color-brass)]">
                    {s.step}
                  </div>
                  <div
                    className="mt-3 text-[24px] leading-tight text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    {s.title}
                  </div>
                  <p
                    className="mt-3 text-[14.5px] leading-[1.65] text-[var(--color-text-dim)]"
                    dangerouslySetInnerHTML={{ __html: s.body }}
                  />
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ─────── EDGE ATTRIBUTION ─────── */}
      <section
        id="edge"
        className="snap-section relative z-10 flex min-h-[calc(100vh-3.75rem)] items-center border-t border-[var(--color-border)]"
      >
        <div className="mx-auto w-full max-w-5xl px-6 py-12">
          <Reveal>
            <div className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
              Edge Attribution
            </div>
            <h2
              className="max-w-3xl"
              style={{
                fontFamily: "var(--font-display), serif",
                fontStyle: "italic",
                fontWeight: 400,
                fontSize: "clamp(32px,4.6vw,52px)",
                letterSpacing: "-0.02em",
                lineHeight: 1.05,
                textWrap: "balance",
              }}
            >
              Where the edge lives.
            </h2>
          </Reveal>

          <div className="mt-14 grid grid-cols-1 gap-px overflow-hidden rounded-[2px] bg-[var(--color-border)] md:grid-cols-3">
            {[
              {
                title: "Directional bias",
                body: "Yesterday&apos;s daily candle gates today&apos;s side. We don&apos;t fade conviction; we fade exhaustion.",
              },
              {
                title: "Fill management",
                body: "Half off at break-even·five. Trail behind structure on the runner. The biggest gains come not from picking — but from holding.",
              },
              {
                title: "Drawdown discipline",
                body: "Three losses cuts position in half. Five losses pauses the system entirely. The book recovers before it scales.",
              },
            ].map((c, i) => (
              <Reveal key={c.title} delay={i * 100}>
                <div className="h-full bg-[var(--color-bg)] p-9 transition-colors duration-500 hover:bg-[var(--color-surface-1)]">
                  <div
                    className="mb-4 text-[24px] text-[var(--color-text)]"
                    style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
                  >
                    {c.title}
                  </div>
                  <p
                    className="text-[15px] leading-[1.7] text-[var(--color-text-dim)]"
                    dangerouslySetInnerHTML={{ __html: c.body }}
                  />
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ─────── CTA + FOOTER (combined into one snap section) ─────── */}
      <section
        id="outro"
        className="snap-section relative z-10 flex min-h-[calc(100vh-3.75rem)] flex-col border-t border-[var(--color-border)] bg-[#070a10]"
      >
        <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center px-6 py-12 text-center">
          <Reveal>
            <h2
              className="mx-auto max-w-2xl"
              style={{
                fontFamily: "var(--font-display), serif",
                fontStyle: "italic",
                fontWeight: 400,
                fontSize: "clamp(32px,4.4vw,48px)",
                letterSpacing: "-0.02em",
                lineHeight: 1.05,
                textWrap: "balance",
              }}
            >
              The numbers are public. The system is live.
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
              Read the playbook. Audit the performance. Reach out if it interests you.
            </p>
          </Reveal>
          <Reveal delay={120}>
            <div className="mt-10 flex flex-wrap justify-center gap-3">
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
                href="/playbook"
                className="inline-flex items-center gap-2 rounded-full border border-[var(--color-brass)]/35 px-7 py-3.5 text-[13px] font-bold uppercase tracking-[0.14em] text-[var(--color-brass)] transition hover:border-[var(--color-brass)] hover:bg-[var(--color-brass)]/10"
              >
                Strategy Playbook
              </Link>
            </div>
          </Reveal>
        </div>

        {/* Inline footer (kept inside #outro so the section snaps as a single unit) */}
        <footer className="relative z-10 border-t border-[var(--color-border)]/70">
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
              <Link href="/playbook" className="transition-colors hover:text-[var(--color-text)]">
                Playbook
              </Link>
              <Link href="/report" className="transition-colors hover:text-[var(--color-text)]">
                Performance
              </Link>
              <Link href="/login" className="transition-colors hover:text-[var(--color-text)]">
                Login
              </Link>
              <a
                href="mailto:subashtrades.in@gmail.com"
                className="transition-colors hover:text-[var(--color-text)]"
              >
                Contact
              </a>
            </div>
          </div>
          <div className="border-t border-[var(--color-border)]/40">
            <p className="mx-auto max-w-6xl px-6 py-3 text-[11.5px] leading-[1.6] text-[var(--color-text-muted)]">
              Backtest results are based on simulated execution against historical OHLC data
              with modeled spread and slippage. Past performance does not guarantee future returns.
              Live trading commenced June 2026.
            </p>
          </div>
        </footer>
      </section>
    </div>
  );
}
