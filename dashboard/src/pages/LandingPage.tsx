import { useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  Gauge,
  AtSign,
  Mail,
  Phone,
  Radio,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import { MidasMark } from "../components/MidasMark";
import { TiltCard } from "../components/TiltCard";

/**
 * Premium, animated, mobile-first landing page for Hand of Midas.
 * Renders with ZERO live data (static marketing) so it loads instantly and
 * works logged-out. Full glass aesthetic, staggered fade-in motion.
 */
export function LandingPage() {
  return (
    <div className="h-full w-full overflow-y-auto overflow-x-hidden bg-bg-base text-ink-primary font-sans">
      <Nav />
      <Hero />
      <Ticker />
      <Features />
      <HowItWorks />
      <Proof />
      <Contact />
      <CTA />
      <Footer />
    </div>
  );
}

/* ============================ NAV ============================ */
function Nav() {
  return (
    <header className="sticky top-0 z-30 backdrop-blur-xl bg-bg-base/70 border-b border-glass-border">
      <div className="max-w-6xl mx-auto flex items-center justify-between px-5 sm:px-8 h-16">
        <div className="flex items-center gap-2.5">
          <MidasMark size={34} animate spinOnHover ariaLabel="Hand of Midas" className="group" />
          <span className="display text-[15px] sm:text-ds-md tracking-[0.14em] text-ink-primary">
            HAND OF MIDAS
          </span>
        </div>
        <nav className="hidden md:flex items-center gap-7 text-ds-sm text-ink-secondary">
          <a href="#features" className="hover:text-ink-primary transition-colors">Features</a>
          <a href="#how" className="hover:text-ink-primary transition-colors">How it works</a>
          <a href="#proof" className="hover:text-ink-primary transition-colors">Track record</a>
          <a href="#contact" className="hover:text-ink-primary transition-colors">Contact</a>
        </nav>
        <div className="flex items-center gap-2.5">
          <Link
            to="/login"
            className="text-ds-sm font-medium text-ink-secondary hover:text-ink-primary transition-colors px-2"
          >
            Log in
          </Link>
          <Link
            to="/login"
            className="glass rounded-full px-4 sm:px-5 py-2 text-ds-sm font-semibold text-ink-primary hover:text-white hover:shadow-ds-hover transition-all"
          >
            Open terminal
          </Link>
        </div>
      </div>
    </header>
  );
}

/* ============================ HERO ============================ */
function Hero() {
  // Pointer parallax: background wash layers drift opposite the cursor, the
  // headline drifts slightly with it — a shallow depth field (skill: perspective).
  const sceneRef = useRef<HTMLElement | null>(null);
  const onMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const el = sceneRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const dx = (e.clientX - r.left) / r.width - 0.5; // -0.5..0.5
    const dy = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--px", dx.toFixed(3));
    el.style.setProperty("--py", dy.toFixed(3));
  }, []);

  return (
    <section
      ref={sceneRef}
      onPointerMove={onMove}
      className="relative overflow-hidden neon-grid tilt-scene"
      style={{ ["--px" as string]: 0, ["--py" as string]: 0 }}
    >
      {/* aurora + washes — drift with pointer for parallax depth */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="anim-aurora absolute -top-1/2 left-1/2 -translate-x-1/2 w-[120vw] h-[120vw] rounded-full opacity-[0.5]"
          style={{ background: "conic-gradient(from 0deg, rgba(255,255,255,0.05), transparent 25%, rgba(255,255,255,0.04) 50%, transparent 75%, rgba(255,255,255,0.05))" }} />
        <div
          className="parallax absolute -top-40 right-0 w-[60vw] h-[60vw] rounded-full bg-[radial-gradient(circle,rgba(232,198,90,0.10),transparent_60%)] blur-[120px]"
          style={{ transform: "translate3d(calc(var(--px) * -42px), calc(var(--py) * -42px), 0)" }}
        />
        <div
          className="parallax absolute bottom-0 -left-40 w-[55vw] h-[55vw] rounded-full bg-white/[0.03] blur-[130px]"
          style={{ transform: "translate3d(calc(var(--px) * 38px), calc(var(--py) * 38px), 0)" }}
        />
      </div>

      <div
        className="parallax relative z-10 max-w-6xl mx-auto px-5 sm:px-8 pt-20 sm:pt-28 pb-16 text-center"
        style={{ transform: "translate3d(calc(var(--px) * 14px), calc(var(--py) * 10px), 0)" }}
      >
        <div className="anim-fade-up inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border border-[#e8c65a]/30 bg-[#e8c65a]/[0.06] text-ds-xs uppercase tracking-widest text-[#e8c65a] mb-8">
          <span className="ds-dot inline-block w-1.5 h-1.5 rounded-full bg-bull" />
          Live now · trading XAUUSD · demo account
        </div>

        <h1 className="anim-fade-up anim-d1 display text-[15vw] sm:text-[10vw] md:text-[6.75rem] leading-[0.9] tracking-tight">
          <span className="text-gold-sheen">Gold</span>
          <span className="text-ink-primary">, traded</span>
          <br />
          <span className="text-ink-muted">on autopilot.</span>
        </h1>

        <p className="anim-fade-up anim-d2 mt-8 max-w-2xl mx-auto text-ds-lg text-ink-secondary leading-relaxed">
          An automated trading desk for gold. It reads the market, sizes every trade to
          your risk, banks profits on the way up, and runs live around the clock —
          proven across <span className="text-ink-primary font-medium">20 years</span> of
          history before a single real order.
        </p>

        <div className="anim-fade-up anim-d3 mt-10 flex flex-col sm:flex-row items-center justify-center gap-3.5">
          <Link
            to="/login"
            state={{ from: "/live" }}
            className="group w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-full px-7 py-3.5 text-ds-md font-semibold text-bg-base bg-gradient-to-r from-[#e8c65a] to-[#f2d67a] hover:from-[#f2d67a] hover:to-[#ffe89a] shadow-[0_0_30px_-8px_rgba(232,198,90,0.6)] transition-all"
          >
            <Zap size={18} strokeWidth={2.5} />
            Launch the terminal
            <ArrowRight size={17} className="group-hover:translate-x-0.5 transition-transform" />
          </Link>
          <Link
            to="/login"
            state={{ from: "/backtest" }}
            className="glass w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-full px-7 py-3.5 text-ds-md font-medium text-ink-primary hover:text-white hover:shadow-ds-hover transition-all"
          >
            <BarChart3 size={18} />
            See 20-year track record
          </Link>
        </div>

        {/* Trust strip — quiet credibility line under the CTAs. */}
        <div className="anim-fade-up anim-d3 mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-ds-xs text-ink-dim">
          {["No look-ahead bias", "Risk-capped every trade", "Backtest = live parity", "Streamed to the second"].map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5">
              <ShieldCheck size={13} className="text-[#e8c65a]/70" />
              {t}
            </span>
          ))}
        </div>

        {/* Productised showcase — a matured "desk preview" card. */}
        <div className="anim-fade-up anim-d4 mt-14 max-w-4xl mx-auto tilt-scene">
          <TiltCard max={5} className="glass-strong rounded-ds-xl overflow-hidden text-left">
            {/* window chrome */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-glass-border bg-glass-subtle">
              <span className="w-2.5 h-2.5 rounded-full bg-bear/70" />
              <span className="w-2.5 h-2.5 rounded-full bg-warn/70" />
              <span className="w-2.5 h-2.5 rounded-full bg-bull/70" />
              <span className="ml-3 text-ds-xs text-ink-muted font-mono">midas · live desk</span>
              <span className="ml-auto inline-flex items-center gap-1.5 text-ds-xs text-bull">
                <span className="ds-dot inline-block w-1.5 h-1.5 rounded-full bg-bull" /> LIVE
              </span>
            </div>
            {/* stat rail */}
            <div className="tilt-layer grid grid-cols-2 sm:grid-cols-4 divide-x divide-glass-border">
              {HERO_STATS.map((s) => (
                <div key={s.label} className="px-5 py-6">
                  <div className={`font-mono text-ds-2xl font-bold ${s.tone}`}>{s.value}</div>
                  <div className="mt-1 text-ds-xs uppercase tracking-wider text-ink-muted">{s.label}</div>
                </div>
              ))}
            </div>
          </TiltCard>
        </div>
      </div>
    </section>
  );
}

/* ============================ TICKER ============================ */
function Ticker() {
  const items = [
    "Trades gold for you", "Never sleeps", "Every trade sized to risk",
    "Banks profit automatically", "20 years proven", "Live positions, streamed",
    "Rules, not emotions", "Books partials on the way up", "Your desk, one screen",
  ];
  const row = [...items, ...items];
  return (
    <div className="relative overflow-hidden border-y border-glass-border py-3.5 bg-glass-subtle">
      <div className="anim-marquee flex gap-8 whitespace-nowrap w-max">
        {row.map((t, i) => (
          <span key={i} className="inline-flex items-center gap-8 text-ds-sm text-ink-muted">
            <span className="w-1 h-1 rounded-full bg-ink-dim" />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ============================ FEATURES ============================ */
function Features() {
  return (
    <section id="features" className="relative max-w-6xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
      <Heading kicker="The desk" title="Everything on one glass surface" />
      <div className="tilt-scene mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {FEATURES.map((f, i) => (
          <TiltCard
            key={f.title}
            max={7}
            className={`group glass rounded-ds-lg p-6 hover:shadow-ds-hover transition-shadow duration-300 anim-fade-up ${["anim-d1","anim-d2","anim-d3","anim-d4","anim-d5","anim-d6"][i] ?? ""}`}
          >
            <div className="tilt-layer">
              <div className="inline-flex p-2.5 rounded-ds bg-glass-strong text-ink-primary group-hover:scale-110 transition-transform">
                <f.icon size={20} />
              </div>
              <div className="mt-4 text-ds-lg font-semibold text-ink-primary">{f.title}</div>
              <div className="mt-2 text-ds-sm text-ink-muted leading-relaxed">{f.body}</div>
            </div>
          </TiltCard>
        ))}
      </div>
    </section>
  );
}

/* ============================ HOW IT WORKS ============================ */
function HowItWorks() {
  return (
    <section id="how" className="relative max-w-5xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
      <Heading kicker="How it works" title="Signal to fill, fully causal" />
      <div className="mt-12 grid grid-cols-1 sm:grid-cols-3 gap-4">
        {STEPS.map((s, i) => (
          <div key={s.title} className="relative glass rounded-ds-lg p-6">
            <div className="font-mono text-ds-3xl font-bold text-ink-dim">{String(i + 1).padStart(2, "0")}</div>
            <div className="mt-2 text-ds-md font-semibold text-ink-primary">{s.title}</div>
            <div className="mt-1.5 text-ds-sm text-ink-muted leading-relaxed">{s.body}</div>
            {i < STEPS.length - 1 && (
              <ArrowRight size={18} className="hidden sm:block absolute -right-3 top-1/2 -translate-y-1/2 text-ink-dim" />
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/* ============================ PROOF ============================ */
function Proof() {
  return (
    <section id="proof" className="relative max-w-6xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
      <div className="glass rounded-ds-xl p-8 sm:p-12 overflow-hidden relative">
        <div className="pointer-events-none absolute -top-20 -right-20 w-80 h-80 rounded-full bg-white/[0.04] blur-[100px]" />
        <div className="relative grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-10 items-center">
          <div>
            <Heading kicker="Track record" title="Proven across two decades" align="left" />
            <p className="mt-5 text-ds-md text-ink-secondary leading-relaxed max-w-lg">
              Backtested tick-by-tick over 20 years of gold, then run live with the exact
              same code path — broker fills reconciled to the cent. No look-ahead, no
              curve-fit, no surprises.
            </p>
            <div className="mt-7 flex flex-wrap gap-2.5">
              {["No look-ahead", "Time-aware close", "Broker-reconciled", "Risk-capped"].map((t) => (
                <span key={t} className="glass rounded-full px-3.5 py-1.5 text-ds-xs text-ink-secondary">
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="tilt-scene grid grid-cols-2 gap-3.5">
            {PROOF_STATS.map((s) => (
              <TiltCard key={s.label} max={10} className="glass rounded-ds-lg px-5 py-5">
                <div className="tilt-layer-deep">
                  <div className={`font-mono text-ds-2xl font-bold ${s.tone}`}>{s.value}</div>
                  <div className="mt-1 text-ds-xs uppercase tracking-wider text-ink-muted">{s.label}</div>
                </div>
              </TiltCard>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ============================ CTA ============================ */
function CTA() {
  return (
    <section className="relative px-5 sm:px-8 py-24 text-center overflow-hidden">
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="w-[70vw] h-[35vw] rounded-full bg-white/[0.05] blur-[130px]" />
      </div>
      <div className="relative z-10 max-w-3xl mx-auto glass rounded-ds-xl px-6 sm:px-10 py-14">
        <Sparkles size={26} className="mx-auto text-ink-secondary mb-5" />
        <h2 className="display text-ds-3xl md:text-[3rem] leading-tight text-ink-primary">
          Watch the edge run <span className="text-sheen">live</span>.
        </h2>
        <p className="mt-4 text-ds-md text-ink-secondary max-w-xl mx-auto">
          Positions, floating P&amp;L, and every gate decision — streamed to the second.
        </p>
        <Link
          to="/live"
          className="mt-8 inline-flex items-center gap-2 rounded-full px-8 py-3.5 text-ds-md font-semibold text-bg-base bg-ink-primary hover:bg-white transition-all"
        >
          <Activity size={18} strokeWidth={2.5} />
          Open the live cockpit
        </Link>
      </div>
    </section>
  );
}

/* ============================ CONTACT ============================ */
const CONTACTS = [
  { icon: Mail, label: "Email", value: "subashtrades.in@gmail.com", href: "mailto:subashtrades.in@gmail.com" },
  { icon: Phone, label: "Phone", value: "+91 99946 05758", href: "tel:+919994605758" },
  { icon: AtSign, label: "Instagram", value: "@subash_mourougayane", href: "https://instagram.com/subash_mourougayane" },
];

function Contact() {
  return (
    <section id="contact" className="relative max-w-6xl mx-auto px-5 sm:px-8 py-20 sm:py-28">
      <Heading kicker="Contact" title="Talk to the desk" />
      <div className="tilt-scene mt-12 grid grid-cols-1 sm:grid-cols-3 gap-4">
        {CONTACTS.map((c) => (
          <TiltCard key={c.label} max={9} className="group glass rounded-ds-lg p-6 hover:shadow-ds-hover transition-shadow">
            <a href={c.href} target={c.label === "Instagram" ? "_blank" : undefined} rel="noreferrer" className="tilt-layer block">
              <div className="inline-flex p-2.5 rounded-ds bg-glass-strong text-[#e8c65a] group-hover:scale-110 transition-transform">
                <c.icon size={20} />
              </div>
              <div className="mt-4 text-ds-xs uppercase tracking-wider text-ink-muted">{c.label}</div>
              <div className="mt-1 text-ds-md font-semibold text-ink-primary break-words group-hover:text-white transition-colors">
                {c.value}
              </div>
            </a>
          </TiltCard>
        ))}
      </div>
    </section>
  );
}

/* ============================ FOOTER ============================ */
function Footer() {
  return (
    <footer className="px-5 sm:px-8 py-10 border-t border-glass-border">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-ds-xs text-ink-dim">
        <div className="flex items-center gap-2">
          <MidasMark size={24} ariaLabel="Hand of Midas" />
          <span className="display tracking-[0.16em] text-ink-muted">HAND OF MIDAS</span>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
          <Link to="/login" className="hover:text-ink-secondary transition-colors">Terminal</Link>
          <a href="mailto:subashtrades.in@gmail.com" className="inline-flex items-center gap-1.5 hover:text-ink-secondary transition-colors">
            <Mail size={13} /> subashtrades.in@gmail.com
          </a>
          <a href="tel:+919994605758" className="inline-flex items-center gap-1.5 hover:text-ink-secondary transition-colors">
            <Phone size={13} /> +91 99946 05758
          </a>
          <a href="https://instagram.com/subash_mourougayane" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 hover:text-ink-secondary transition-colors">
            <AtSign size={13} /> @subash_mourougayane
          </a>
          <span>Demo · not investment advice</span>
        </div>
      </div>
    </footer>
  );
}

/* ============================ shared ============================ */
function Heading({ kicker, title, align = "center" }: { kicker: string; title: string; align?: "center" | "left" }) {
  return (
    <div className={align === "center" ? "text-center" : "text-left"}>
      <div className="text-ds-xs uppercase tracking-[0.28em] text-ink-muted">{kicker}</div>
      <h2 className="mt-2.5 display text-ds-2xl md:text-ds-3xl text-ink-primary tracking-tight">{title}</h2>
    </div>
  );
}

/* ============================ content ============================ */
const HERO_STATS = [
  { value: "20yr", label: "backtested", tone: "text-ink-primary" },
  { value: "1.31", label: "profit factor", tone: "text-bull" },
  { value: "0Δ", label: "backtest = live", tone: "text-ink-primary" },
  { value: "M15", label: "intraday base", tone: "text-ink-secondary" },
];

const PROOF_STATS = [
  { value: "25,902", label: "trades tested", tone: "text-ink-primary" },
  { value: "47.1%", label: "win rate", tone: "text-ink-primary" },
  { value: "18 / 21", label: "positive years", tone: "text-bull" },
  { value: "1.5%", label: "risk / trade", tone: "text-ink-secondary" },
];

const FEATURES = [
  { icon: Activity, title: "Live cockpit", body: "Positions-first desk. Floating P&L, booked partials, and account equity stream tick-by-tick over WebSocket." },
  { icon: BarChart3, title: "Backtests", body: "20 years of gold with filter-aware analytics, an equity curve, and a P&L calendar you can slice by session and hold-time." },
  { icon: BookOpen, title: "Trade journal", body: "Every trade replayed bar-by-bar — entry geometry, MFE / MAE, and the full gate → fill → exit timeline." },
  { icon: Radio, title: "Signal feed", body: "The decision funnel in real time: pivots, setups, confirmations, and exactly where each candidate was filtered out." },
  { icon: ShieldCheck, title: "Causal by design", body: "Every feature comes from closed bars before entry. A 15-point line-by-line causality audit — all pass." },
  { icon: Gauge, title: "Broker parity", body: "The same code drives backtest and live. Fills, partial take-profits, and P&L reconciled against broker deal history." },
];

const STEPS = [
  { title: "Read the structure", body: "Detect swing pivots on closed M15 bars, then build a Fibonacci retracement zone — never using future data." },
  { title: "Confirm & size", body: "Wait for price to enter the zone with confirmation, then size the position to a fixed 1.5% risk of equity." },
  { title: "Execute & manage", body: "Fire the order live, bank a partial at +1R, trail the stop to breakeven, and let the rest run to target." },
];
