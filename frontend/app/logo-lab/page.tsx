"use client";

import Link from "next/link";

/* ═══════════════════════════════════════════════════════════════════════════
   LOGO LAB — final review

   Brief:
     Luxury quant fund mark for "Hand of Midas"
     Bridgewater meets private bank · institutional · editorial-luxe
     Geometric minimal · 16px favicon-safe · slate (#0A0E14) + emerald (#10B981)
     Concept: diamond from two converging vectors at reversal point
     Subtle emerald accent at center = alpha generation
     No hands, no $, no candlesticks, no MLM/crypto vibes

   4 concepts, each built to brief, shown in 5 production contexts:
     1. Hero (centered on slate, breathing room)
     2. Size scale (16/24/32/48/96 px)
     3. Wordmark lockup (Fraunces Italic alongside)
     4. Favicon mock (browser tab simulation)
     5. Deck-cover mock (in context with type)
   ═══════════════════════════════════════════════════════════════════════════ */

const SLATE = "#0A0E14";
const SLATE_2 = "#11161F";
const SLATE_3 = "#161C25";
const BORDER = "#1F2733";
const E = "#10B981";
const E_HI = "#34D399";
const E_DIM = "#047857";
const TEXT = "#F1F3F6";
const TEXT_DIM = "#C8CDD6";
const TEXT_MUTED = "#8C95A4";

/* ═══════════════════════════════════════════════════════════════════════════
   THE FOUR MARKS
   Each is a single self-contained SVG. ViewBox 64×64. No external assets.
   ═══════════════════════════════════════════════════════════════════════════ */

/**
 * MARK A — "Convergence"
 * Two thin vectors (ascending + descending) meet at a single point.
 * The intersection produces a perfect rhombus through negative space.
 * A small emerald square sits exactly at the intersection center.
 * Most negative-space-driven of the four.
 */
const MarkA = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
    {/* Ascending vector — bottom-left to top-right of diamond apex */}
    <path
      d="M14 50 L32 8"
      stroke={TEXT}
      strokeWidth="1.4"
      strokeLinecap="round"
      opacity={0.92}
    />
    {/* Descending vector — bottom-right back through apex (creates the X meeting) */}
    <path
      d="M50 50 L32 8"
      stroke={TEXT}
      strokeWidth="1.4"
      strokeLinecap="round"
      opacity={0.92}
    />
    {/* The implied diamond — drawn very thin, brass-emerald, gives the rhombus form */}
    <path
      d="M32 8 L50 32 L32 56 L14 32 Z"
      stroke={E}
      strokeWidth="1.2"
      strokeLinejoin="miter"
      opacity={0.65}
    />
    {/* Center alpha point — small filled square rotated 45° */}
    <rect x="29" y="29" width="6" height="6" fill={E} transform="rotate(45 32 32)" />
  </svg>
);

/**
 * MARK B — "Apex"
 * A precise rhombus rendered as a thin emerald outline.
 * Two ultra-fine guide lines cross at center (the convergence axis).
 * A single small emerald dot at the exact center = alpha.
 * Most institutional / private-bank feel.
 */
const MarkB = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
    {/* Outer rhombus — thin precise outline */}
    <path
      d="M32 10 L52 32 L32 54 L12 32 Z"
      stroke={E}
      strokeWidth="1.4"
      strokeLinejoin="miter"
      fill="none"
    />
    {/* Faint convergence guides — vertical + horizontal axes through center */}
    <line x1="32" y1="14" x2="32" y2="50" stroke={TEXT_DIM} strokeWidth="0.4" opacity={0.25} />
    <line x1="16" y1="32" x2="48" y2="32" stroke={TEXT_DIM} strokeWidth="0.4" opacity={0.25} />
    {/* Center alpha dot */}
    <circle cx="32" cy="32" r="2.2" fill={E} />
    <circle cx="32" cy="32" r="1" fill={E_HI} />
  </svg>
);

/**
 * MARK C — "Reversal"
 * Two vectors approach the apex from opposite directions and stop just shy
 * of meeting — the gap IS the reversal moment. The implied diamond is in
 * negative space. Emerald accent sits in the gap.
 * Most concept-true to the brief; reads as "a meeting about to happen."
 */
const MarkC = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
    {/* Top half: rhombus formed by 2 strokes meeting at apex */}
    <path
      d="M14 32 L32 12"
      stroke={TEXT}
      strokeWidth="1.6"
      strokeLinecap="round"
    />
    <path
      d="M50 32 L32 12"
      stroke={TEXT}
      strokeWidth="1.6"
      strokeLinecap="round"
    />
    {/* Bottom half: same shape, but emerald — the reversal */}
    <path
      d="M14 32 L32 52"
      stroke={E}
      strokeWidth="1.6"
      strokeLinecap="round"
    />
    <path
      d="M50 32 L32 52"
      stroke={E}
      strokeWidth="1.6"
      strokeLinecap="round"
    />
    {/* Subtle emerald midpoint — the convergence */}
    <circle cx="32" cy="32" r="2" fill={E_HI} />
  </svg>
);

/**
 * MARK D — "Plinth"
 * A solid filled rhombus in muted slate, with a precise emerald-edge
 * highlight on its top-right facet only — the way light falls on a
 * cut gemstone. Most "cut diamond / private-bank" feel.
 * Single tone gradient avoided; pure flat color for institutional grade.
 */
const MarkD = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
    {/* Filled diamond body — deep emerald, low chroma */}
    <path d="M32 10 L52 32 L32 54 L12 32 Z" fill={E_DIM} />
    {/* Top-right facet — emerald light edge */}
    <path d="M32 10 L52 32 L32 32 Z" fill={E} />
    {/* Top-left facet — slightly brighter emerald (the "lit" edge) */}
    <path d="M32 10 L32 32 L12 32 Z" fill={E_HI} opacity={0.85} />
    {/* Inner thin precision lines */}
    <path d="M32 10 L32 54 M12 32 L52 32" stroke={SLATE} strokeWidth="0.6" />
    {/* Center alpha point */}
    <circle cx="32" cy="32" r="1.6" fill={SLATE} />
  </svg>
);

/**
 * MARK E — "Spire" (user-provided concept)
 * Open rhombus outline (off-white). The top and bottom apex corners
 * extend OUTWARD into thin tapering spires beyond the rhombus body.
 * A small filled emerald rhombus sits at the exact geometric center.
 *
 * The spires give the mark vertical drama and a sigil-like quality
 * (compass / heraldic mark) without crossing into ornament. The center
 * gem holds the alpha. Highest verticality of the five concepts —
 * stands out at lockup-size and at hero scale; works at 16px because
 * the spires + rhombus collapse into a single tall diamond glyph.
 */
const MarkE = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
    {/* Open rhombus body — drawn as four thin strokes that taper at the
        top and bottom apexes (we use stroke for cleaner small-size rendering
        than a filled outline path). */}
    {/* Left edge — bottom-left to top apex (which extends as a spire above) */}
    <path
      d="M16 32 L32 18"
      stroke={TEXT}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="miter"
    />
    {/* Right edge — bottom-right to top apex */}
    <path
      d="M48 32 L32 18"
      stroke={TEXT}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="miter"
    />
    {/* Bottom-left edge — top-left to bottom apex */}
    <path
      d="M16 32 L32 46"
      stroke={TEXT}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="miter"
    />
    {/* Bottom-right edge */}
    <path
      d="M48 32 L32 46"
      stroke={TEXT}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="miter"
    />
    {/* TOP SPIRE — extends upward from the top apex */}
    <path
      d="M32 18 L32 4"
      stroke={TEXT}
      strokeWidth="1.4"
      strokeLinecap="round"
    />
    {/* BOTTOM SPIRE — extends downward from the bottom apex */}
    <path
      d="M32 46 L32 60"
      stroke={TEXT}
      strokeWidth="1.4"
      strokeLinecap="round"
    />
    {/* Center alpha gem — small filled emerald rhombus */}
    <path d="M32 28 L36 32 L32 36 L28 32 Z" fill={E} />
  </svg>
);

/* ═══════════════════════════════════════════════════════════════════════════
   PRODUCTION CONTEXTS — show each mark in real environments
   ═══════════════════════════════════════════════════════════════════════════ */

/** Hero — centered on a generous slate canvas, breathing room. */
function Hero({ Mark, name, code }: { Mark: React.FC<{ size?: number }>; name: string; code: string }) {
  return (
    <div
      className="relative overflow-hidden rounded-[2px] border"
      style={{ borderColor: BORDER, background: SLATE }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.08]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(60,51,39,0.5) 1px,transparent 1px),linear-gradient(90deg,rgba(60,51,39,0.5) 1px,transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />
      <div className="relative flex h-72 items-center justify-center">
        <Mark size={140} />
      </div>
      <div className="relative flex items-baseline justify-between border-t px-7 py-4" style={{ borderColor: BORDER }}>
        <div
          className="text-[19px] italic"
          style={{ fontFamily: "var(--font-display), serif", color: TEXT }}
        >
          {name}
        </div>
        <div className="text-[10px] uppercase tracking-[0.22em]" style={{ color: TEXT_MUTED }}>
          {code}
        </div>
      </div>
    </div>
  );
}

/** Size scale — 5 sizes side-by-side, with px labels. */
function SizeScale({ Mark }: { Mark: React.FC<{ size?: number }> }) {
  const sizes = [16, 24, 32, 48, 96];
  return (
    <div
      className="rounded-[2px] border bg-[var(--color-bg)] px-6 py-7"
      style={{ borderColor: BORDER }}
    >
      <div className="text-[10px] uppercase tracking-[0.22em]" style={{ color: TEXT_MUTED }}>
        Scale stress test
      </div>
      <div className="mt-5 flex flex-wrap items-end gap-12">
        {sizes.map((s) => (
          <div key={s} className="flex flex-col items-center gap-3">
            <div className="flex h-24 items-center justify-center">
              <Mark size={s} />
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: TEXT_MUTED }}>
              {s}px
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Wordmark lockup — mark next to "Hand of Midas" in Fraunces italic, three sizes. */
function Lockup({ Mark }: { Mark: React.FC<{ size?: number }> }) {
  const variants = [
    { mark: 14, text: 19 },
    { mark: 22, text: 28 },
    { mark: 36, text: 44 },
  ];
  return (
    <div
      className="rounded-[2px] border bg-[var(--color-bg)] p-7"
      style={{ borderColor: BORDER }}
    >
      <div className="text-[10px] uppercase tracking-[0.22em]" style={{ color: TEXT_MUTED }}>
        Wordmark lockup
      </div>
      <div className="mt-5 flex flex-col gap-7">
        {variants.map((v) => (
          <div key={v.mark} className="flex items-center gap-4">
            <Mark size={v.mark} />
            <span
              className="italic tracking-tight"
              style={{
                fontFamily: "var(--font-display), serif",
                fontSize: v.text,
                color: TEXT,
              }}
            >
              Hand of Midas
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Favicon mock — a fake browser tab. */
function FaviconMock({ Mark }: { Mark: React.FC<{ size?: number }> }) {
  return (
    <div
      className="rounded-[2px] border bg-[var(--color-bg)] p-7"
      style={{ borderColor: BORDER }}
    >
      <div className="text-[10px] uppercase tracking-[0.22em]" style={{ color: TEXT_MUTED }}>
        Favicon · browser tab
      </div>
      <div className="mt-5 flex items-center gap-2 rounded-t-md px-3 pt-2 pb-2.5" style={{ background: SLATE_2 }}>
        <div className="flex gap-1.5">
          <div className="h-3 w-3 rounded-full bg-[#ff5f57]" />
          <div className="h-3 w-3 rounded-full bg-[#febc2e]" />
          <div className="h-3 w-3 rounded-full bg-[#28c840]" />
        </div>
      </div>
      <div className="flex items-center gap-2 px-3 py-2" style={{ background: SLATE_3 }}>
        <Mark size={16} />
        <span className="text-[12px]" style={{ color: TEXT_DIM }}>
          Hand of Midas — Quantitative Commodities
        </span>
        <span className="ml-auto text-[14px]" style={{ color: TEXT_MUTED }}>
          ×
        </span>
      </div>
      <div className="px-3 py-3" style={{ background: SLATE }}>
        <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: TEXT_MUTED }}>
          midas.subashtrades.in
        </div>
      </div>
    </div>
  );
}

/** Deck-cover mock — mark + headline + tagline, like /deck cover. */
function DeckMock({ Mark }: { Mark: React.FC<{ size?: number }> }) {
  return (
    <div
      className="relative overflow-hidden rounded-[2px] border"
      style={{ borderColor: BORDER, background: SLATE }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(800px circle at 50% 0%, rgba(16,185,129,0.04), transparent 60%)",
        }}
      />
      <div className="relative px-10 py-12">
        <div className="flex items-center gap-3">
          <Mark size={36} />
          <span
            className="italic tracking-tight"
            style={{ fontFamily: "var(--font-display), serif", fontSize: 24, color: TEXT }}
          >
            Hand of Midas
          </span>
        </div>
        <div
          className="mt-12 italic"
          style={{
            fontFamily: "var(--font-display), serif",
            fontSize: 56,
            lineHeight: 1.02,
            letterSpacing: "-0.025em",
            color: TEXT,
          }}
        >
          Quantitative
          <br />
          commodities.
        </div>
        <div className="mt-6 max-w-md text-[14.5px] leading-[1.7]" style={{ color: TEXT_DIM }}>
          A trading system for Gold and Brent Crude. Four engines, one thesis,
          twenty-one years of out-of-sample receipts.
        </div>
        <div className="mt-10 flex items-center gap-2 text-[10px] uppercase tracking-[0.22em]" style={{ color: TEXT_MUTED }}>
          <span style={{ color: E }}>●</span>
          Investor deck · 2026
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PAGE
   ═══════════════════════════════════════════════════════════════════════════ */

const CONCEPTS = [
  {
    code: "A",
    name: "Convergence",
    Mark: MarkA,
    blurb:
      "Two vectors meet at the diamond apex. The rhombus emerges from their intersection — the form is half-implied, half-drawn. The center alpha-mark is the precise moment of meeting.",
    notes: "Most negative-space driven · Strong at large sizes · Apex is the focal point",
  },
  {
    code: "B",
    name: "Apex",
    Mark: MarkB,
    blurb:
      "A precise rhombus outline with the convergence axes drawn faintly through center. The single emerald dot at the geometric center is the alpha point. Closest to a coat-of-arms / private-bank seal.",
    notes: "Most institutional · Reads as a seal · Scales perfectly to 16px",
  },
  {
    code: "C",
    name: "Reversal",
    Mark: MarkC,
    blurb:
      "Top half drawn in off-white (the move up); bottom half in emerald (the reversal). The diamond is split by direction. The emerald midpoint is the moment the trade flips.",
    notes: "Strongest concept-to-brief · Tells the story · Two-tone, slightly more visual energy",
  },
  {
    code: "D",
    name: "Plinth",
    Mark: MarkD,
    blurb:
      "A cut gem rendered as flat facets — three planes of emerald (deep, mid, light) hinting at how light falls on a precision-cut diamond. No gradient — pure flat color, hedge-fund grade.",
    notes: "Most luxury · Reads as a gemstone · Cleanest at 32px+",
  },
  {
    code: "E",
    name: "Spire",
    Mark: MarkE,
    blurb:
      "An open rhombus outline with the top and bottom apex corners extended outward into thin tapering spires. A small emerald gem sits at the exact geometric center. The spires give the mark vertical drama and a sigil-like quality — heraldic without ornament.",
    notes: "Highest verticality · Heraldic / compass feel · Spires + rhombus collapse to a tall diamond at 16px",
  },
] as const;

export default function LogoLabPage() {
  return (
    <div className="min-h-screen" style={{ background: SLATE, color: TEXT }}>
      {/* Faint grid background */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-0 opacity-[0.10]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(60,51,39,0.5) 1px,transparent 1px),linear-gradient(90deg,rgba(60,51,39,0.5) 1px,transparent 1px)",
          backgroundSize: "84px 84px",
          maskImage: "radial-gradient(ellipse at 50% 30%, black 30%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse at 50% 30%, black 30%, transparent 75%)",
        }}
      />

      {/* Top bar */}
      <header
        className="relative z-10 border-b"
        style={{ borderColor: BORDER }}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Link href="/" className="flex items-center gap-3">
            <span
              aria-hidden
              className="inline-block h-3.5 w-3.5 rotate-45"
              style={{ background: E, boxShadow: "0 0 14px rgba(16,185,129,0.45)" }}
            />
            <span
              className="text-[19px] italic tracking-tight"
              style={{ fontFamily: "var(--font-display), serif" }}
            >
              Hand of Midas
            </span>
            <span
              className="ml-3 text-[10px] uppercase tracking-[0.22em]"
              style={{ color: TEXT_MUTED }}
            >
              ← current placeholder
            </span>
          </Link>
          <nav className="text-[14px]" style={{ color: TEXT_DIM }}>
            <Link href="/" className="hover:text-[var(--color-text)]">
              ← back to site
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-5xl px-6 py-16 md:py-20">
        {/* Title block */}
        <div>
          <div
            className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em]"
            style={{ color: E }}
          >
            Logo Lab · v2 · brief-driven
          </div>
          <h1
            className="italic"
            style={{
              fontFamily: "var(--font-display), serif",
              fontSize: "clamp(48px,7vw,84px)",
              lineHeight: 0.98,
              letterSpacing: "-0.03em",
            }}
          >
            Four marks.
          </h1>
          <p
            className="mt-7 max-w-2xl text-[16.5px] leading-[1.7]"
            style={{ color: TEXT_DIM }}
          >
            Each built strictly to brief: institutional, restrained, geometric. Diamond from two
            converging vectors at a market reversal. Emerald accent at center. Bridgewater meets
            private bank — no hands, no candlesticks, no MLM gloss.
          </p>
          <p className="mt-4 max-w-2xl text-[14px]" style={{ color: TEXT_MUTED }}>
            Every concept rendered in 5 production contexts. Pick by ID at the bottom.
          </p>
        </div>

        {/* Concepts */}
        <div className="mt-20 space-y-24">
          {CONCEPTS.map((c) => (
            <section key={c.code} className="space-y-6">
              {/* Header */}
              <div className="flex items-baseline justify-between gap-6">
                <div>
                  <div
                    className="text-[10px] uppercase tracking-[0.22em]"
                    style={{ color: E }}
                  >
                    Concept {c.code}
                  </div>
                  <h2
                    className="mt-2 italic"
                    style={{
                      fontFamily: "var(--font-display), serif",
                      fontSize: "clamp(32px,5vw,56px)",
                      lineHeight: 1.02,
                      letterSpacing: "-0.025em",
                    }}
                  >
                    {c.name}
                  </h2>
                  <p
                    className="mt-4 max-w-2xl text-[14.5px] leading-[1.65]"
                    style={{ color: TEXT_DIM }}
                  >
                    {c.blurb}
                  </p>
                  <p
                    className="mt-3 text-[12px]"
                    style={{ color: TEXT_MUTED }}
                  >
                    {c.notes}
                  </p>
                </div>
              </div>

              {/* Hero + scale */}
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Hero Mark={c.Mark} name={`Hand of Midas`} code={c.code} />
                <SizeScale Mark={c.Mark} />
              </div>

              {/* Lockup + favicon */}
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
                <Lockup Mark={c.Mark} />
                <FaviconMock Mark={c.Mark} />
              </div>

              {/* Deck cover full width */}
              <DeckMock Mark={c.Mark} />
            </section>
          ))}
        </div>

        {/* Footer / pick */}
        <section
          className="mt-24 rounded-[2px] border p-10"
          style={{ borderColor: BORDER, background: SLATE_2 }}
        >
          <div
            className="text-[11.5px] font-semibold uppercase tracking-[0.22em]"
            style={{ color: E }}
          >
            Pick a mark
          </div>
          <h2
            className="mt-3 italic"
            style={{
              fontFamily: "var(--font-display), serif",
              fontSize: "clamp(28px,4vw,42px)",
              letterSpacing: "-0.02em",
            }}
          >
            Tell me the ID.
          </h2>
          <p
            className="mt-4 max-w-2xl text-[14.5px] leading-[1.7]"
            style={{ color: TEXT_DIM }}
          >
            Reply with the concept code (A, B, C, D, or E). I&apos;ll wire it across nav, footer,
            favicon, and the deck/report/playbook hero in one commit. Or say &ldquo;none&rdquo;
            and I&apos;ll iterate further.
          </p>
          <div className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-5">
            {CONCEPTS.map((c) => (
              <div
                key={c.code}
                className="flex items-center justify-between rounded-[2px] border px-5 py-4"
                style={{ borderColor: BORDER, background: SLATE }}
              >
                <c.Mark size={28} />
                <div className="ml-4 flex-1">
                  <div
                    className="text-[14px] italic"
                    style={{ fontFamily: "var(--font-display), serif" }}
                  >
                    {c.name}
                  </div>
                </div>
                <div
                  className="text-[10px] uppercase tracking-[0.22em]"
                  style={{ color: TEXT_MUTED }}
                >
                  {c.code}
                </div>
              </div>
            ))}
          </div>
        </section>

        <div className="mt-12 text-[11.5px]" style={{ color: TEXT_MUTED }}>
          Logo Lab v2 · concepts only · drop in via Edit when picked · this page is unlinked, won&apos;t ship to nav.
        </div>
      </main>
    </div>
  );
}
