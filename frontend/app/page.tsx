"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/* ═══════════════════════════════════════════════════════════════════
   UTILITY COMPONENTS
   ═══════════════════════════════════════════════════════════════════ */

function AnimatedNumber({ target, prefix = "", suffix = "", duration = 2000, decimals = 0 }: {
  target: number; prefix?: string; suffix?: string; duration?: number; decimals?: number;
}) {
  const [value, setValue] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const animated = useRef(false);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !animated.current) {
        animated.current = true;
        const start = performance.now();
        const animate = (now: number) => {
          const progress = Math.min((now - start) / duration, 1);
          const eased = 1 - Math.pow(1 - progress, 3);
          setValue(target * eased);
          if (progress < 1) requestAnimationFrame(animate);
        };
        requestAnimationFrame(animate);
      }
    }, { threshold: 0.3 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [target, duration]);

  return (
    <div ref={ref}>
      {prefix}{decimals > 0 ? value.toFixed(decimals) : Math.round(value).toLocaleString()}{suffix}
    </div>
  );
}

function FadeIn({ children, delay = 0, className = "" }: { children: React.ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setVisible(true);
    }, { threshold: 0.1 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? "translateY(0)" : "translateY(24px)",
        transition: `opacity 0.7s ease ${delay}ms, transform 0.7s ease ${delay}ms`,
      }}
    >
      {children}
    </div>
  );
}

function GoldParticles() {
  const particles = Array.from({ length: 24 }, (_, i) => ({
    x: Math.random() * 100,
    y: Math.random() * 100,
    size: 2 + Math.random() * 3,
    delay: Math.random() * 5,
    duration: 4 + Math.random() * 4,
    opacity: 0.15 + Math.random() * 0.25,
  }));

  return (
    <div className="hide-mobile" style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
      {particles.map((p, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
            background: "#e8c300",
            boxShadow: `0 0 ${p.size * 2}px rgba(232, 195, 0, 0.6)`,
            opacity: p.opacity,
            animation: `float-candle ${p.duration}s ease-in-out ${p.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}

function LiveTradeFeed() {
  const trades = [
    { pair: "XAU/USD", side: "LONG", entry: "2,341.50", pnl: "+$1,847", strat: "Alpha-Sweep" },
    { pair: "BCO/USD", side: "SHORT", entry: "78.42", pnl: "+$562", strat: "Mean-Rev" },
    { pair: "XAU/USD", side: "SHORT", entry: "2,368.20", pnl: "+$921", strat: "Cross-Market" },
    { pair: "BCO/USD", side: "LONG", entry: "76.15", pnl: "+$389", strat: "Alpha-Sweep" },
    { pair: "XAU/USD", side: "LONG", entry: "2,298.80", pnl: "+$1,204", strat: "Mean-Rev" },
    { pair: "BCO/USD", side: "SHORT", entry: "81.33", pnl: "+$715", strat: "Cross-Market" },
    { pair: "XAU/USD", side: "LONG", entry: "2,315.60", pnl: "+$1,093", strat: "Alpha-Sweep" },
    { pair: "BCO/USD", side: "LONG", entry: "74.88", pnl: "+$428", strat: "Mean-Rev" },
  ];
  const doubled = [...trades, ...trades];

  return (
    <div style={{ overflow: "hidden", position: "relative", margin: "0 auto", maxWidth: 700 }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 60, background: "linear-gradient(90deg, #0a0d12, transparent)", zIndex: 2 }} />
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 60, background: "linear-gradient(270deg, #0a0d12, transparent)", zIndex: 2 }} />
      <div className="trade-feed-scroll" style={{ display: "flex", gap: 16, padding: "12px 0", width: "max-content" }}>
        {doubled.map((t, i) => (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "8px 14px",
            background: "#0e1117", border: "1px solid #1a1f28", whiteSpace: "nowrap",
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: t.pair.includes("XAU") ? "#e8c300" : "#4fc3f7" }}>{t.pair}</span>
            <span style={{ fontSize: 10, fontWeight: 600, color: t.side === "LONG" ? "#00e87b" : "#ff3e3e" }}>{t.side}</span>
            <span style={{ fontSize: 10, color: "#9ca3b4" }}>{t.entry}</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#00e87b" }}>{t.pnl}</span>
            <span style={{ fontSize: 9, color: "#6b7280" }}>{t.strat}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   LANDING PAGE
   ═══════════════════════════════════════════════════════════════════ */

export default function LandingPage() {
  const router = useRouter();
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handleMouse = (e: MouseEvent) => {
      setMousePos({ x: e.clientX, y: e.clientY });
    };
    window.addEventListener("mousemove", handleMouse);
    return () => window.removeEventListener("mousemove", handleMouse);
  }, []);

  return (
    <div className="landing-page" style={{ background: "#0a0d12", minHeight: "100vh", width: "100%", overflow: "hidden" }}>

      {/* Ambient gradient that follows mouse */}
      <div
        className="hide-mobile"
        style={{
          position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
          background: `radial-gradient(800px circle at ${mousePos.x}px ${mousePos.y}px, rgba(232, 195, 0, 0.03), transparent 60%)`,
        }}
      />

      {/* Grid background */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0, opacity: 0.35,
        backgroundImage: `linear-gradient(rgba(37, 42, 51, 0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(37, 42, 51, 0.3) 1px, transparent 1px)`,
        backgroundSize: "60px 60px",
      }} />

      {/* ═══ HERO ═══ */}
      <section style={{ position: "relative", zIndex: 1, padding: "100px 24px 80px", textAlign: "center" }}>
        <GoldParticles />

        <FadeIn>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "6px 16px", border: "1px solid #252a33", background: "#111318", marginBottom: 32 }}>
            <div className="t-pulse" style={{ width: 6, height: 6, background: "#e8c300" }} />
            <span style={{ fontSize: 11, color: "#9ca3b4", textTransform: "uppercase", letterSpacing: "0.12em" }}>No Phantom Fills. Honest Execution Only.</span>
          </div>
        </FadeIn>

        <FadeIn delay={100}>
          <div style={{ fontSize: 52, marginBottom: 12 }}>&#x1F91A;</div>
          <h1 className="landing-hero-title" style={{
            fontSize: "clamp(40px, 7vw, 72px)", fontWeight: 800, letterSpacing: "-0.02em",
            background: "linear-gradient(135deg, #e8c300, #ffdf4a, #e8c300)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            marginBottom: 16, lineHeight: 1.1,
          }}>
            HAND OF MIDAS
          </h1>
        </FadeIn>

        <FadeIn delay={200}>
          <p className="landing-hero-subtitle" style={{ fontSize: "clamp(14px, 2vw, 20px)", color: "#9ca3b4", maxWidth: 600, margin: "0 auto 12px", lineHeight: 1.6 }}>
            Everything it touches turns to gold.
          </p>
          <p style={{ fontSize: 13, color: "#6b7280", maxWidth: 500, margin: "0 auto" }}>
            Fixed SL/TP. No trailing stops. No phantom fills.
            <br />
            <span style={{ color: "#c8cdd5" }}>Gold + Oil — 20 years validated.</span>
          </p>
        </FadeIn>

        <FadeIn delay={250}>
          <div style={{ margin: "40px auto 0", maxWidth: 700, position: "relative" }}>
            <LiveTradeFeed />
          </div>
        </FadeIn>

        <FadeIn delay={350}>
          <div className="landing-cta-buttons" style={{ display: "flex", gap: 12, justifyContent: "center", marginTop: 40, flexWrap: "wrap" }}>
            <button
              onClick={() => router.push("/login")}
              style={{
                background: "linear-gradient(135deg, #e8c300, #c5a500)", color: "#000", border: "none",
                padding: "14px 36px", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
                display: "inline-flex", alignItems: "center", gap: 8, transition: "transform 0.2s, box-shadow 0.2s",
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 32px rgba(232, 195, 0, 0.3)"; }}
              onMouseLeave={e => { e.currentTarget.style.transform = ""; e.currentTarget.style.boxShadow = ""; }}
            >
              Enter Dashboard &rarr;
            </button>
            <button
              onClick={() => window.open("/midas-report.html", "_blank")}
              style={{
                background: "transparent", color: "#00e87b", border: "1px solid #00e87b55",
                padding: "14px 36px", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
                display: "inline-flex", alignItems: "center", gap: 8, transition: "all 0.2s",
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = "#00e87b"; e.currentTarget.style.background = "#00e87b10"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "#00e87b55"; e.currentTarget.style.background = "transparent"; }}
            >
              Midas Backtest Report
            </button>
            <button
              onClick={() => router.push("/login")}
              style={{
                background: "transparent", color: "#e8c300", border: "1px solid #e8c30055",
                padding: "14px 36px", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
                display: "inline-flex", alignItems: "center", gap: 8, transition: "all 0.2s",
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = "#e8c300"; e.currentTarget.style.background = "#e8c30010"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "#e8c30055"; e.currentTarget.style.background = "transparent"; }}
            >
              Login
            </button>
          </div>
        </FadeIn>
      </section>

      {/* ═══ STATS TICKER ═══ */}
      <section style={{ position: "relative", zIndex: 1, borderTop: "1px solid #1a1f28", borderBottom: "1px solid #1a1f28", padding: "32px 24px", background: "#0c0e14" }}>
        <div className="landing-stats-ticker" style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", maxWidth: 1100, margin: "0 auto", gap: 0 }}>
          {[
            { value: 640000, prefix: "$", label: "Total P&L", sub: "20yr combined", color: "#e8c300" },
            { value: 2084, prefix: "", label: "Total Trades", sub: "Gold + Oil", color: "#4fc3f7" },
            { value: 65.4, suffix: "%", label: "Win Rate", sub: "Honest fills only", color: "#00e87b", decimals: 1 },
            { value: 4.50, suffix: "x", label: "Profit Factor", sub: "Combined strategies", color: "#e8c300", decimals: 2 },
            { value: 20, suffix: "yr", label: "Backtested", sub: "2006-2026", color: "#4fc3f7" },
          ].map(({ value, prefix, suffix, label, sub, color, decimals }) => (
            <div key={label} style={{ textAlign: "center", padding: "16px 12px", borderRight: "1px solid #1a1f28" }}>
              <div style={{ fontSize: "clamp(20px, 3vw, 28px)", fontWeight: 800, color }}>
                <AnimatedNumber target={value} prefix={prefix || ""} suffix={suffix || ""} decimals={decimals || 0} />
              </div>
              <div style={{ fontSize: 10, color: "#9ca3b4", textTransform: "uppercase", letterSpacing: "0.1em", marginTop: 4 }}>{label}</div>
              <div style={{ fontSize: 9, color: "#6b7280", marginTop: 2 }}>{sub}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ═══ INSTRUMENTS ═══ */}
      <section style={{ position: "relative", zIndex: 1, padding: "80px 24px", maxWidth: 1100, margin: "0 auto" }}>
        <FadeIn>
          <h3 style={{ fontSize: "clamp(24px, 4vw, 36px)", color: "#f0f2f5", fontWeight: 700, marginBottom: 8, letterSpacing: "-0.01em", textAlign: "center" }}>
            Two Markets. One Engine.
          </h3>
          <p style={{ fontSize: 14, color: "#9ca3b4", textAlign: "center", maxWidth: 500, margin: "0 auto 48px" }}>
            Commodities-focused algorithmic trading on the world's most liquid instruments.
          </p>
        </FadeIn>

        <FadeIn delay={100}>
          <div className="landing-instruments-grid" style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 20, maxWidth: 800, margin: "0 auto" }}>
            {/* Gold card */}
            <div style={{ background: "#111318", border: "1px solid #1a1f28", padding: "32px 24px", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg, #e8c300, transparent)" }} />
              <div style={{ fontSize: 32, marginBottom: 16 }}>&#x1F947;</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#e8c300", marginBottom: 4 }}>XAU/USD</div>
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 20 }}>Gold — The king of commodities</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Trades</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#c8cdd5" }}>1,238</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Win Rate</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#00e87b" }}>63.2%</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Profit Factor</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#e8c300" }}>3.83</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Total P&L</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#00e87b" }}>$325K</div>
                </div>
              </div>
            </div>

            {/* Oil card */}
            <div style={{ background: "#111318", border: "1px solid #1a1f28", padding: "32px 24px", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg, #4fc3f7, transparent)" }} />
              <div style={{ fontSize: 32, marginBottom: 16 }}>&#x1F6E2;&#xFE0F;</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "#4fc3f7", marginBottom: 4 }}>BCO/USD</div>
              <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 20 }}>Brent Crude Oil — Black gold</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Trades</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#c8cdd5" }}>846</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Win Rate</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#00e87b" }}>74.0%</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Profit Factor</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#4fc3f7" }}>7.95</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: "#6b7280", textTransform: "uppercase" }}>Total P&L</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: "#00e87b" }}>$315K</div>
                </div>
              </div>
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ═══ STRATEGY BREAKDOWN ═══ */}
      <section style={{ position: "relative", zIndex: 1, padding: "80px 24px", borderTop: "1px solid #1a1f28", background: "#0c0e14" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <FadeIn>
            <h3 style={{ fontSize: "clamp(24px, 4vw, 36px)", color: "#f0f2f5", fontWeight: 700, marginBottom: 8, textAlign: "center", letterSpacing: "-0.01em" }}>
              Three Strategies. Zero Phantom Fills.
            </h3>
            <p style={{ fontSize: 14, color: "#9ca3b4", textAlign: "center", maxWidth: 550, margin: "0 auto 48px" }}>
              Each strategy uses fixed SL/TP with honest bar-level fill logic. No trailing stop tricks.
            </p>
          </FadeIn>

          <FadeIn delay={100}>
            <div className="landing-features-row" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
              {[
                {
                  name: "Alpha-Sweep",
                  pf: "3.40",
                  color: "#e8c300",
                  desc: "Liquidity sweep detection at key levels. Enters on sweep confirmation with structure break. High conviction, fewer trades.",
                  conditions: ["Liquidity sweep at HTF level", "Market structure shift", "Fair value gap entry", "Fixed 2:1 R:R"],
                },
                {
                  name: "Mean-Rev",
                  pf: "2.80",
                  color: "#00e87b",
                  desc: "Mean reversion at statistical extremes. RSI + Bollinger Band deviation with momentum confirmation for reversal entries.",
                  conditions: ["RSI(14) < 25 or > 75", "Price outside 2.5 std BB", "Momentum divergence", "Fixed 1.5:1 R:R"],
                },
                {
                  name: "Cross-Market",
                  pf: "2.10",
                  color: "#4fc3f7",
                  desc: "Gold-Oil correlation regime trades. Exploits temporary decorrelation between XAU and BCO for convergence plays.",
                  conditions: ["Correlation breakdown detected", "Regime shift confirmation", "Spread divergence > 2 std", "Fixed 1.8:1 R:R"],
                },
              ].map(({ name, pf, color, desc, conditions }) => (
                <div key={name} style={{ background: "#111318", border: "1px solid #1a1f28", padding: "28px 22px", position: "relative" }}>
                  <div style={{ position: "absolute", top: 0, left: 0, width: 3, height: "100%", background: color }} />
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#f0f2f5" }}>{name}</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color, padding: "2px 8px", border: `1px solid ${color}40`, background: `${color}10` }}>PF {pf}</span>
                  </div>
                  <p style={{ fontSize: 12, color: "#9ca3b4", lineHeight: 1.6, marginBottom: 16 }}>{desc}</p>
                  <div style={{ borderTop: "1px solid #1a1f28", paddingTop: 12 }}>
                    {conditions.map((c, i) => (
                      <div key={i} style={{ fontSize: 11, color: "#6b7280", marginBottom: 6, display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ color, fontSize: 8 }}>&#x25CF;</span>
                        {c}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </FadeIn>
        </div>
      </section>

      {/* ═══ KEY DIFFERENTIATOR ═══ */}
      <section style={{ position: "relative", zIndex: 1, padding: "60px 24px", borderTop: "1px solid #1a1f28" }}>
        <div style={{ maxWidth: 800, margin: "0 auto" }}>
          <FadeIn>
            <div style={{
              background: "#111318", border: "1px solid #252a33", padding: "40px 32px",
              position: "relative", overflow: "hidden",
            }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg, #e8c300, #00e87b, #4fc3f7)" }} />
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 11, color: "#e8c300", textTransform: "uppercase", letterSpacing: "0.15em", marginBottom: 16 }}>
                  The Midas Difference
                </div>
                <h4 style={{ fontSize: "clamp(18px, 3vw, 24px)", color: "#f0f2f5", fontWeight: 700, marginBottom: 16, lineHeight: 1.4 }}>
                  No trailing stops. No phantom fills.<br />Fixed SL/TP. Honest fills only.
                </h4>
                <p style={{ fontSize: 13, color: "#9ca3b4", lineHeight: 1.7, maxWidth: 550, margin: "0 auto" }}>
                  Most backtests show inflated results because they fill trailing stops at impossible intra-bar prices.
                  Hand Of Midas uses only fixed stop-loss and take-profit levels, filled at the bar's actual OHLC prices.
                  What you see in backtest is what you get in live.
                </p>
              </div>
            </div>
          </FadeIn>
        </div>
      </section>

      {/* ═══ ARCHITECTURE OVERVIEW ═══ */}
      <section style={{ position: "relative", zIndex: 1, padding: "80px 24px", borderTop: "1px solid #1a1f28", background: "#0c0e14" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <FadeIn>
            <h3 style={{ fontSize: "clamp(20px, 3vw, 28px)", color: "#f0f2f5", fontWeight: 700, marginBottom: 40, textAlign: "center" }}>
              How It Works
            </h3>
          </FadeIn>

          <FadeIn delay={100}>
            <div className="landing-arch-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
              {[
                { step: "01", title: "Data Pipeline", desc: "20 years of H1 OHLCV data for Gold and Oil. Self-updating CSV pipeline appends new bars hourly from OANDA.", color: "#e8c300" },
                { step: "02", title: "Signal Engine", desc: "Three independent strategy engines scan every bar. Fixed entry conditions — no ML, no curve-fitting, no optimization.", color: "#00e87b" },
                { step: "03", title: "Honest Fills", desc: "Bar-level fill simulation: SL/TP checked against actual High/Low. No intra-bar assumptions. What backtests show is real.", color: "#4fc3f7" },
                { step: "04", title: "OANDA Execution", desc: "Live execution via OANDA REST API. Fixed SL/TP set at order time. No modifications, no trailing. Pure set-and-forget.", color: "#ff6b6b" },
              ].map(({ step, title, desc, color }) => (
                <div key={step} style={{ padding: "24px 20px", background: "#111318", border: "1px solid #1a1f28", borderTop: `2px solid ${color}` }}>
                  <div style={{ fontSize: 11, color, fontWeight: 700, marginBottom: 8, letterSpacing: "0.1em" }}>{step}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#f0f2f5", marginBottom: 8 }}>{title}</div>
                  <div style={{ fontSize: 12, color: "#9ca3b4", lineHeight: 1.6 }}>{desc}</div>
                </div>
              ))}
            </div>
          </FadeIn>
        </div>
      </section>

      {/* ═══ CTA FOOTER ═══ */}
      <section style={{ position: "relative", zIndex: 1, padding: "80px 24px", textAlign: "center", borderTop: "1px solid #1a1f28" }}>
        <FadeIn>
          <h3 style={{ fontSize: "clamp(20px, 3vw, 28px)", color: "#f0f2f5", fontWeight: 700, marginBottom: 12 }}>
            Login to start trading
          </h3>
          <p style={{ fontSize: 13, color: "#9ca3b4", marginBottom: 32 }}>
            Live on OANDA demo. Validated over 20 years. Zero phantom fills.
          </p>
        </FadeIn>

        <FadeIn delay={100}>
          <div className="landing-cta-buttons" style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <button
              onClick={() => router.push("/login")}
              style={{
                background: "linear-gradient(135deg, #e8c300, #c5a500)", color: "#000", border: "none",
                padding: "14px 36px", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
                display: "inline-flex", alignItems: "center", gap: 8, transition: "transform 0.2s, box-shadow 0.2s",
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 32px rgba(232, 195, 0, 0.3)"; }}
              onMouseLeave={e => { e.currentTarget.style.transform = ""; e.currentTarget.style.boxShadow = ""; }}
            >
              Login &rarr;
            </button>
            <button
              onClick={() => router.push("/login")}
              style={{
                background: "transparent", color: "#9ca3b4", border: "1px solid #252a33",
                padding: "14px 36px", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase",
                transition: "all 0.2s",
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = "#4fc3f7"; e.currentTarget.style.color = "#4fc3f7"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = "#252a33"; e.currentTarget.style.color = "#9ca3b4"; }}
            >
              View Backtests
            </button>
          </div>
        </FadeIn>

        <FadeIn delay={300}>
          <div style={{ marginTop: 60, paddingTop: 40, borderTop: "1px solid #1a1f28" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, marginBottom: 12 }}>
              <span style={{ fontSize: 18 }}>&#x1F91A;</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: "#e8c300", letterSpacing: "0.08em" }}>HAND OF MIDAS</span>
            </div>
            <p style={{ fontSize: 11, color: "#6b7280" }}>
              Built with honest fills. Validated without phantom trades. Ready for live.
            </p>
            <p style={{ fontSize: 10, color: "#4b5563", marginTop: 8 }}>
              Gold + Oil Algorithmic Trading Engine
            </p>
            <p style={{ fontSize: 10, color: "#6b7280", marginTop: 12 }}>
              Contact: <a href="mailto:subashtrades.in@gmail.com" style={{ color: "#4fc3f7", textDecoration: "none" }}>subashtrades.in@gmail.com</a>
            </p>
          </div>
        </FadeIn>
      </section>
    </div>
  );
}
