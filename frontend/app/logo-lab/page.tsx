"use client";

import Link from "next/link";

/* ─────────────────────────────────────────────────────────────
   LOGO LAB — internal review page
   Direction 2: Midas mythology
   Direction 3: Trading-floor archetype
   Each concept renders at 4 sizes (16, 32, 64, 128 px) + as a
   nav-bar mark next to "Hand of Midas" wordmark for context.
   Not linked from nav. Visit /logo-lab directly.
   ───────────────────────────────────────────────────────────── */

/* Base palette — match the live site */
const E = "#10b981"; // emerald (primary brass)
const E_HI = "#34d399"; // light emerald
const E_DIM = "#047857"; // dark emerald

/* ===== DIRECTION 2 — MIDAS MYTHOLOGY ===== */

/** 2A. Hand silhouette + single gem in palm.
 *  Stylized open palm (top-down), gem in center.
 */
const Logo2A = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    {/* Open palm — five-finger silhouette, simplified */}
    <path
      d="M14 32 C14 28, 16 22, 18 18 C19 16, 21 16, 22 18 L22 30 L24 30 L24 14 C24 12, 26 12, 27 14 L27 30 L29 30 L29 12 C29 10, 31 10, 32 12 L32 30 L34 30 L34 14 C34 12, 36 12, 37 14 L37 30 L39 30 L39 18 C40 16, 42 16, 43 18 C45 22, 47 28, 47 32 C47 44, 41 50, 32 50 C23 50, 14 44, 14 32 Z"
      fill={E_DIM}
      stroke={E}
      strokeWidth="0.8"
    />
    {/* Gem in palm — diamond shape */}
    <path d="M32 30 L37 35 L32 42 L27 35 Z" fill={E} stroke={E_HI} strokeWidth="0.6" />
    {/* Gem internal facet */}
    <path d="M32 30 L32 42 M27 35 L37 35" stroke={E_HI} strokeWidth="0.4" opacity={0.7} />
    {/* Glow */}
    <circle cx="32" cy="35" r="2" fill={E_HI} opacity={0.5} />
  </svg>
);

/** 2B. Crown + droplet — King Midas crown, single gold droplet.
 *  3-point crown, droplet falling from center peak.
 */
const Logo2B = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    {/* Crown band */}
    <rect x="16" y="36" width="32" height="6" fill={E_DIM} />
    {/* Crown points: 3 triangles */}
    <path d="M16 36 L20 22 L24 36 Z" fill={E} />
    <path d="M24 36 L32 14 L40 36 Z" fill={E_HI} />
    <path d="M40 36 L44 22 L48 36 Z" fill={E} />
    {/* Crown gems on points */}
    <circle cx="20" cy="22" r="1.5" fill={E_HI} />
    <circle cx="32" cy="14" r="2" fill="#fff" opacity={0.8} />
    <circle cx="44" cy="22" r="1.5" fill={E_HI} />
    {/* Gold droplet falling from center peak */}
    <path d="M32 46 Q34 50, 32 54 Q30 50, 32 46 Z" fill={E} />
  </svg>
);

/** 2C. Touch-spreading-gold — central point with 4 concentric rings.
 *  Geometric, abstract, scales tiny.
 */
const Logo2C = ({ size = 64 }: { size?: number; animate?: boolean }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    {/* 4 expanding rings */}
    <circle cx="32" cy="32" r="26" stroke={E_DIM} strokeWidth="1" fill="none" opacity={0.35} />
    <circle cx="32" cy="32" r="18" stroke={E} strokeWidth="1.2" fill="none" opacity={0.55} />
    <circle cx="32" cy="32" r="11" stroke={E_HI} strokeWidth="1.4" fill="none" opacity={0.8} />
    <circle cx="32" cy="32" r="5" fill={E} />
    <circle cx="32" cy="32" r="2.5" fill={E_HI} />
  </svg>
);

/** 2D. Animated touch-spreading-gold (variant of 2C, with pulse). */
const Logo2D = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    <circle cx="32" cy="32" r="5" fill={E} />
    <circle cx="32" cy="32" r="2.5" fill={E_HI} />
    {[11, 18, 26].map((r, i) => (
      <circle
        key={r}
        cx="32"
        cy="32"
        r={r}
        stroke={E}
        strokeWidth="1.2"
        fill="none"
        opacity={0.6}
      >
        <animate
          attributeName="r"
          values={`${r};${r + 6};${r}`}
          dur="3.6s"
          begin={`${i * 1.2}s`}
          repeatCount="indefinite"
        />
        <animate
          attributeName="opacity"
          values="0.6;0;0.6"
          dur="3.6s"
          begin={`${i * 1.2}s`}
          repeatCount="indefinite"
        />
      </circle>
    ))}
  </svg>
);

/* ===== DIRECTION 3 — TRADING-FLOOR ARCHETYPE ===== */

/** 3A. Candlestick pair — bull (up) + bear (down), abstract.
 */
const Logo3A = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    {/* Wicks */}
    <line x1="22" y1="12" x2="22" y2="52" stroke={E_DIM} strokeWidth="1.2" />
    <line x1="42" y1="12" x2="42" y2="52" stroke={E_DIM} strokeWidth="1.2" />
    {/* Bull body (up, emerald, taller) */}
    <rect x="16" y="20" width="12" height="22" fill={E} />
    {/* Bear body (down, dim emerald, shorter) */}
    <rect x="36" y="28" width="12" height="14" fill={E_DIM} stroke={E} strokeWidth="0.8" />
  </svg>
);

/** 3B. Sweep arrow + reversal — arrow that hooks back.
 *  Literal strategy diagram: thrust up, then fade down (or vice versa).
 */
const Logo3B = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    {/* Sweep arrow — up then hook down */}
    <path
      d="M14 44 L24 22 L34 30 L34 18 L48 18"
      stroke={E}
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    {/* Arrowhead at the reversal */}
    <path
      d="M48 18 L42 14 M48 18 L42 22"
      stroke={E_HI}
      strokeWidth="2.5"
      strokeLinecap="round"
    />
    {/* Sweep dot at peak (the wick) */}
    <circle cx="34" cy="18" r="2" fill={E_HI} />
  </svg>
);

/** 3C. Range box + sweep wick + reversal arrow.
 *  Miniaturized strategy setup: dashed box, wick puncturing, arrow hooking back.
 */
const Logo3C = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    {/* Range box */}
    <rect
      x="14"
      y="24"
      width="36"
      height="16"
      stroke={E_DIM}
      strokeWidth="1.2"
      strokeDasharray="2 2"
      fill="none"
    />
    {/* Sweep wick — punches above the range */}
    <line x1="36" y1="14" x2="36" y2="32" stroke={E_HI} strokeWidth="2" strokeLinecap="round" />
    {/* Reversal arrow — hooks down through the range */}
    <path
      d="M36 32 Q36 44, 24 48"
      stroke={E}
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    {/* Arrowhead */}
    <path d="M24 48 L28 46 M24 48 L26 52" stroke={E} strokeWidth="2.2" strokeLinecap="round" />
    {/* Wick top sweep dot */}
    <circle cx="36" cy="14" r="1.8" fill={E_HI} />
  </svg>
);

/** 3D. Animated sweep — wick draws in, then arrow draws back. */
const Logo3D = ({ size = 64 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    <rect
      x="14"
      y="24"
      width="36"
      height="16"
      stroke={E_DIM}
      strokeWidth="1.2"
      strokeDasharray="2 2"
      fill="none"
    />
    <line
      x1="36"
      y1="32"
      x2="36"
      y2="14"
      stroke={E_HI}
      strokeWidth="2"
      strokeLinecap="round"
      strokeDasharray="20"
      strokeDashoffset="20"
    >
      <animate
        attributeName="stroke-dashoffset"
        from="20"
        to="0"
        dur="0.8s"
        begin="0s;cycle.end+1.5s"
        fill="freeze"
        id="wick"
      />
    </line>
    <path
      d="M36 32 Q36 44, 24 48"
      stroke={E}
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
      strokeDasharray="22"
      strokeDashoffset="22"
    >
      <animate
        attributeName="stroke-dashoffset"
        from="22"
        to="0"
        dur="0.7s"
        begin="wick.end+0.1s"
        fill="freeze"
      />
    </path>
    <circle cx="36" cy="14" r="1.8" fill={E_HI} opacity="0">
      <animate attributeName="opacity" from="0" to="1" dur="0.3s" begin="wick.end" fill="freeze" />
    </circle>
    {/* Reset cycle */}
    <animate id="cycle" attributeName="opacity" from="1" to="1" dur="0.01s" begin="wick.end+1.4s" />
  </svg>
);

/* ─────────────────────────────────────────────────────────────
   Concept rendering helpers
   ───────────────────────────────────────────────────────────── */

const SIZES = [16, 32, 64, 128];

function ConceptRow({
  id,
  name,
  description,
  Component,
  isAnimated = false,
}: {
  id: string;
  name: string;
  description: string;
  Component: React.FC<{ size?: number }>;
  isAnimated?: boolean;
}) {
  return (
    <div className="rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-7">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <div
            className="text-[20px] text-[var(--color-text)]"
            style={{ fontFamily: "var(--font-display), serif", fontStyle: "italic" }}
          >
            {name}
            {isAnimated ? (
              <span className="ml-3 text-[10px] uppercase tracking-[0.18em] text-[var(--color-brass)]">
                ⏵ animated
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-[var(--color-text-dim)]">
            {description}
          </p>
        </div>
        <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--color-text-muted)]">
          {id}
        </div>
      </div>

      {/* Size scale row */}
      <div className="mt-7 flex flex-wrap items-end gap-10 border-y border-[var(--color-border)]/60 bg-[var(--color-bg)]/50 px-4 py-6">
        {SIZES.map((s) => (
          <div key={s} className="flex flex-col items-center gap-2">
            <div className="flex h-32 items-center justify-center">
              <Component size={s} />
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-text-muted)]">
              {s}px
            </div>
          </div>
        ))}
      </div>

      {/* Nav-bar mock — what it'd look like in the real header */}
      <div className="mt-5 flex items-center gap-3 rounded-[2px] border border-[var(--color-border)]/60 bg-[var(--color-bg)] px-5 py-4">
        <Component size={14} />
        <span
          className="text-[19px] italic tracking-tight text-[var(--color-text)]"
          style={{ fontFamily: "var(--font-display), serif" }}
        >
          Hand of Midas
        </span>
        <span className="ml-auto text-[10px] uppercase tracking-[0.2em] text-[var(--color-text-muted)]">
          nav-bar mock @ 14px
        </span>
      </div>

      {/* Footer mock */}
      <div className="mt-3 flex items-center gap-2.5 rounded-[2px] border border-[var(--color-border)]/60 bg-[var(--color-bg)] px-5 py-4">
        <Component size={10} />
        <span
          className="text-[14px] italic text-[var(--color-text-dim)]"
          style={{ fontFamily: "var(--font-display), serif" }}
        >
          Hand of Midas — by Subash Mourougayane
        </span>
        <span className="ml-auto text-[10px] uppercase tracking-[0.2em] text-[var(--color-text-muted)]">
          footer mock @ 10px
        </span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   PAGE
   ───────────────────────────────────────────────────────────── */

export default function LogoLabPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
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

      <header className="relative z-10 border-b border-[var(--color-border)]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <Link href="/" className="flex items-center gap-3">
            <span
              aria-hidden
              className="inline-block h-3.5 w-3.5 rotate-45 bg-[var(--color-brass)]"
              style={{ boxShadow: "0 0 14px rgba(16,185,129,0.45)" }}
            />
            <span
              className="text-[19px] italic tracking-tight"
              style={{ fontFamily: "var(--font-display), serif" }}
            >
              Hand of Midas
            </span>
            <span className="ml-3 text-[10px] uppercase tracking-[0.2em] text-[var(--color-text-muted)]">
              ← current placeholder mark
            </span>
          </Link>
          <nav className="text-[14px] text-[var(--color-text-dim)]">
            <Link href="/" className="hover:text-[var(--color-text)]">
              ← back
            </Link>
          </nav>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-5xl px-6 py-16">
        <div>
          <div className="mb-2 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
            Logo Lab · review only · not in nav
          </div>
          <h1
            className="text-[clamp(40px,6vw,72px)] italic"
            style={{
              fontFamily: "var(--font-display), serif",
              letterSpacing: "-0.025em",
              lineHeight: 1.02,
            }}
          >
            Pick the mark.
          </h1>
          <p className="mt-5 max-w-2xl text-[16.5px] leading-[1.7] text-[var(--color-text-dim)]">
            Two directions, multiple variants each. Each concept renders at four sizes
            (16/32/64/128 px) plus inline next to the wordmark in nav and footer mocks. SVG
            only — same emerald palette as live site, drop-in replaceable.
          </p>
        </div>

        {/* Direction 2 */}
        <section className="mt-16">
          <div className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
            Direction 2
          </div>
          <h2
            className="text-[clamp(28px,4vw,42px)] italic"
            style={{ fontFamily: "var(--font-display), serif", letterSpacing: "-0.02em" }}
          >
            Midas mythology.
          </h2>
          <p className="mt-4 max-w-2xl text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]">
            King Midas turned everything to gold. The mark nods to the source story — hand,
            crown, or the touch itself.
          </p>

          <div className="mt-10 grid grid-cols-1 gap-6">
            <ConceptRow
              id="2A"
              name="Hand + gem"
              description="Open palm silhouette with a single emerald gem in the center. Most literal interpretation. Renders cleanly above 24px; gets noisy at 16px."
              Component={Logo2A}
            />
            <ConceptRow
              id="2B"
              name="Crown + droplet"
              description="Three-point crown with gem-set points and a falling gold droplet. References Midas as king and his touch as transformation. Reads as luxury / monarchy."
              Component={Logo2B}
            />
            <ConceptRow
              id="2C"
              name="Touch — concentric rings"
              description="Pure abstract: a central emerald point with four expanding rings. The Midas touch as a wave outward. Most geometric; scales perfectly to favicon size."
              Component={Logo2C}
            />
            <ConceptRow
              id="2D"
              name="Touch — animated pulse"
              description="Same as 2C but the rings pulse outward continuously. Use as nav mark with subtle motion; not for static print."
              Component={Logo2D}
              isAnimated
            />
          </div>
        </section>

        {/* Direction 3 */}
        <section className="mt-20">
          <div className="mb-3 text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
            Direction 3
          </div>
          <h2
            className="text-[clamp(28px,4vw,42px)] italic"
            style={{ fontFamily: "var(--font-display), serif", letterSpacing: "-0.02em" }}
          >
            Trading-floor archetype.
          </h2>
          <p className="mt-4 max-w-2xl text-[14.5px] leading-[1.7] text-[var(--color-text-dim)]">
            What the strategy actually does, drawn miniature. Less luxury, more trader. Honest
            about being a trading system, not a fund.
          </p>

          <div className="mt-10 grid grid-cols-1 gap-6">
            <ConceptRow
              id="3A"
              name="Candlestick pair"
              description="Bull and bear bodies with wicks. Universal trader-floor visual. Direct but generic — every trading product uses some variant of this."
              Component={Logo3A}
            />
            <ConceptRow
              id="3B"
              name="Sweep arrow + reversal"
              description="An arrow that thrusts up, peaks, then hooks back down. Literally draws the strategy: sweep + fade. Distinctive and meaningful — but reads as 'arrow' at small sizes."
              Component={Logo3B}
            />
            <ConceptRow
              id="3C"
              name="Range box + wick + reversal"
              description="The full setup miniaturized: dashed range, wick punching above, reversal arrow hooking back. Most strategy-true. Loses detail below 32px."
              Component={Logo3C}
            />
            <ConceptRow
              id="3D"
              name="Range + wick — animated draw"
              description="Same as 3C but draws in: wick first, then reversal arrow. The strategy unfolds every load. Ideal for hero / loading state, not for nav."
              Component={Logo3D}
              isAnimated
            />
          </div>
        </section>

        {/* Verdict guide */}
        <section className="mt-24 rounded-[2px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-8">
          <div className="text-[11.5px] font-semibold uppercase tracking-[0.22em] text-[var(--color-brass)]">
            How to choose
          </div>
          <h2
            className="mt-3 text-[clamp(24px,3vw,32px)] italic"
            style={{ fontFamily: "var(--font-display), serif", letterSpacing: "-0.02em" }}
          >
            Three lenses.
          </h2>
          <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-3">
            {[
              {
                t: "Memorability",
                b: "Will an investor remember the mark a week after seeing it once? 2C and 3B win — geometric and unique. 2A and 3A risk feeling generic.",
              },
              {
                t: "Scale to 16px",
                b: "Favicon and tiny nav use need to read clearly at 16px. 2C, 2D, 3A scale best. 2A and 3C lose detail at small sizes.",
              },
              {
                t: "Strategy alignment",
                b: "Does the mark mean something specific to the product? 3B and 3C tell the actual strategy story (sweep + fade). 2A/2B reference the brand name only.",
              },
            ].map((c) => (
              <div key={c.t} className="rounded-[2px] border border-[var(--color-border)]/60 p-5">
                <div
                  className="text-[16px] italic text-[var(--color-text)]"
                  style={{ fontFamily: "var(--font-display), serif" }}
                >
                  {c.t}
                </div>
                <p className="mt-2 text-[13.5px] leading-[1.65] text-[var(--color-text-dim)]">{c.b}</p>
              </div>
            ))}
          </div>
          <p className="mt-8 max-w-2xl text-[13.5px] leading-relaxed text-[var(--color-text-muted)]">
            My pick if forced: <span className="text-[var(--color-text)]">2C (concentric rings)</span> for the
            base mark — pure geometric, scales perfectly, abstractly meaningful — paired with{" "}
            <span className="text-[var(--color-text)]">3D (animated sweep)</span> as the hero / loading
            artifact. Best of both directions.
          </p>
        </section>

        <div className="mt-16 border-t border-[var(--color-border)] pt-8 text-[11.5px] text-[var(--color-text-muted)]">
          Logo Lab · concepts only · drop in via Edit when you pick · this page is unlinked, won&apos;t ship
          to nav.
        </div>
      </main>
    </div>
  );
}
