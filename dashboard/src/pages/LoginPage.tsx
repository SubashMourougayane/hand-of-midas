import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { ArrowRight, Loader2, Lock, LogIn } from "lucide-react";
import { SpireMark } from "../components/SpireMark";
import { Guardian, GuardianExpr } from "../components/Guardian";
import { GoldParticles } from "../components/GoldParticles";
import { useAuth } from "../lib/auth";

// Rotating cheeky sub-lines — deterministic pick per minute (no module-scope RNG).
const QUIPS = [
  "The vault only opens for the right hands.",
  "No password, no gold. That's the whole trick.",
  "King Midas kept his desk locked too.",
  "A guardian watches this door. Be nice.",
  "Alchemy pending — enter the magic words.",
];

const WRONG_LINES = [
  "Nope. The gold stays put. 🪙",
  "The guardian says: nice try.",
  "Even Midas fat-fingered sometimes.",
  "The vault yawned. Wrong combination.",
  "Access denied. The coins are giggling.",
];

// Guardian reaction escalates with consecutive wrong attempts.
function exprForAttempt(n: number): GuardianExpr {
  if (n <= 1) return "mischief";
  if (n === 2) return "cool";
  if (n === 3) return "mischief";
  if (n === 4) return "facepalm";
  return "suspicious";
}

type Phase = "idle" | "checking" | "wrong" | "celebrate" | "unlocking" | "shatter";

export function LoginPage() {
  const { token, ready, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from || "/live";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [guardianEmerge, setGuardianEmerge] = useState(false);
  const [guardianExpr, setGuardianExpr] = useState<GuardianExpr>("idle");
  const [guardianWag, setGuardianWag] = useState(false);
  const [laugh, setLaugh] = useState(false);
  const [burst, setBurst] = useState(0);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const timers = useRef<number[]>([]);

  const quip = useMemo(() => QUIPS[Math.floor((Date.now() / 60000) % QUIPS.length)], []);

  // Already authed on ARRIVAL → skip the wall. Snapshot once so a fresh login
  // (which sets the token mid-animation) does NOT trigger this instant bounce —
  // the cinematic runs, then navigates manually in playCorrect().
  const hadTokenOnMount = useRef(!!token);
  useEffect(() => {
    if (ready && hadTokenOnMount.current) nav(from, { replace: true });
  }, [ready, from, nav]);

  // Idle guardian peek — every ~9s it slowly looks out, then hides.
  useEffect(() => {
    if (phase !== "idle") return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;
    const loop = window.setInterval(() => {
      setGuardianExpr("curious");
      setGuardianEmerge(true);
      const t1 = window.setTimeout(() => setGuardianEmerge(false), 2200);
      timers.current.push(t1);
    }, 9000);
    return () => clearInterval(loop);
  }, [phase]);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };
  useEffect(() => () => clearTimers(), []);

  // Pointer-tilt the vault card (skill: perspective).
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = cardRef.current;
    if (!el || phase === "shatter") return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.setProperty("--ry", `${(px - 0.5) * 8}deg`);
    el.style.setProperty("--rx", `${(0.5 - py) * 8}deg`);
    el.style.setProperty("--mx", `${px * 100}%`);
    el.style.setProperty("--my", `${py * 100}%`);
  };
  const onLeave = () => {
    const el = cardRef.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  function playWrong(nextAttempt: number) {
    const expr = exprForAttempt(nextAttempt);
    // suspense → guardian emerges → reacts → drops → field shakes
    const t0 = window.setTimeout(() => {
      setGuardianExpr(expr);
      setGuardianEmerge(true);
    }, 700);
    const t1 = window.setTimeout(() => setLaugh(true), 1300);
    const t2 = window.setTimeout(() => setGuardianWag(expr === "mischief" || expr === "cool"), 1500);
    const t3 = window.setTimeout(() => {
      setLaugh(false);
      setGuardianWag(false);
      setGuardianEmerge(false);
    }, 3200);
    const t4 = window.setTimeout(() => {
      // shake the card + show message
      const el = cardRef.current;
      if (el) {
        el.classList.remove("login-shake");
        void el.offsetWidth;
        el.classList.add("login-shake");
      }
      setError(WRONG_LINES[(nextAttempt - 1) % WRONG_LINES.length]);
      setPhase("idle");
    }, 3300);
    timers.current.push(t0, t1, t2, t3, t4);
  }

  function playCorrect() {
    // guardian proud → dive → molten cracks build → slow shatter → route.
    // Deliberately unhurried so the vault-blast lands with weight.
    setGuardianExpr("proud");
    setGuardianEmerge(true);
    const t0 = window.setTimeout(() => setGuardianEmerge(false), 2100);
    const t1 = window.setTimeout(() => {
      setPhase("unlocking"); // molten cracks charging (longer build-up)
    }, 2300);
    const t2 = window.setTimeout(() => {
      setPhase("shatter"); // shatter + burst
      setBurst((b) => b + 1);
    }, 4100);
    const t3 = window.setTimeout(() => nav(from, { replace: true }), 6000);
    timers.current.push(t0, t1, t2, t3);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (phase !== "idle") return;
    setError(null);
    setPhase("checking");
    try {
      await login(username, password);
      setPhase("celebrate");
      playCorrect();
    } catch {
      const next = attempts + 1;
      setAttempts(next);
      setPhase("wrong");
      playWrong(next);
    }
  }

  const busy = phase === "checking";
  const sealing = phase === "celebrate" || phase === "unlocking" || phase === "shatter";

  return (
    <div className="h-full w-full overflow-y-auto overflow-x-hidden bg-bg-base text-ink-primary font-sans flex items-center justify-center px-5 py-6 tilt-scene relative">
      {/* ambient gold field */}
      <div className="pointer-events-none absolute inset-0 neon-grid opacity-60" />
      <div className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 w-[70vw] h-[70vw] rounded-full bg-[radial-gradient(circle,rgba(232,198,90,0.10),transparent_60%)] blur-[130px]" />
      <GoldParticles burst={burst} density={36} className="absolute inset-0 w-full h-full" />

      {/* full-screen gold flash on shatter */}
      {phase === "shatter" && (
        <div className="pointer-events-none absolute inset-0 z-20 vault-flash bg-[radial-gradient(circle,rgba(255,243,196,0.9),rgba(232,198,90,0.3)_40%,transparent_70%)]" />
      )}

      <div className="relative z-10 w-full max-w-md">
        {/* Guardian lives at the top edge of the card (peeks out of its compartment) */}
        <Guardian
          emerge={guardianEmerge}
          expr={guardianExpr}
          wag={guardianWag}
          className={laugh ? "laugh" : ""}
        />

        <div
          ref={cardRef}
          onPointerMove={onMove}
          onPointerLeave={onLeave}
          className={`tilt-card relative glass-strong rounded-ds-xl p-8 sm:p-10 ${
            phase === "unlocking" ? "vault-charging" : ""
          } ${phase === "shatter" ? "vault-shatter" : ""}`}
        >
          <span className="tilt-glare" aria-hidden />
          {phase === "unlocking" && <span className="vault-crack-line" aria-hidden />}

          <div className="tilt-layer-deep flex flex-col items-center text-center">
            {/* Vault seal — lock breathes idle, coin flips on unlock */}
            <div
              className={`relative flex items-center justify-center w-20 h-20 rounded-full bg-gradient-to-br from-[#3a2f10] to-[#1a1608] border border-[#5a4a18]/50 shadow-[0_0_40px_-8px_rgba(232,198,90,0.6)] mb-6 ${
                sealing ? "coin-flip" : "seal-breathe"
              }`}
            >
              {sealing ? (
                <SpireMark size={40} bodyColor="#e8c65a" ariaLabel="Unlocked" />
              ) : (
                <Lock size={30} className="text-[#e8c65a]" strokeWidth={1.8} />
              )}
            </div>

            <h1 className="display text-ds-2xl tracking-[0.06em] text-ink-primary">
              {sealing ? "Vault opening…" : "Hand of Midas"}
            </h1>
            <p className="mt-2 text-ds-sm text-ink-muted min-h-[20px]">
              {sealing ? "Forging your desk from gold ✨" : quip}
            </p>

            {!sealing && (
              <form onSubmit={submit} className="w-full mt-7 space-y-3 text-left">
                <label className="block">
                  <span className="text-ds-xs uppercase tracking-wider text-ink-muted">Email</span>
                  <input
                    type="text"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="you@subashtrades.in"
                    className="mt-1.5 w-full rounded-ds bg-glass border border-glass-border px-3.5 py-2.5 text-ds-md text-ink-primary placeholder:text-ink-dim focus:outline-none focus:border-[#e8c65a]/60 focus:shadow-[0_0_0_3px_rgba(232,198,90,0.12)] transition-all"
                  />
                </label>
                <label className="block">
                  <span className="text-ds-xs uppercase tracking-wider text-ink-muted">Secret words</span>
                  <input
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••"
                    className="mt-1.5 w-full rounded-ds bg-glass border border-glass-border px-3.5 py-2.5 text-ds-md text-ink-primary placeholder:text-ink-dim focus:outline-none focus:border-[#e8c65a]/60 focus:shadow-[0_0_0_3px_rgba(232,198,90,0.12)] transition-all"
                  />
                </label>

                <div className="min-h-[20px]">
                  {error && <p className="text-ds-sm text-bear anim-fade-up">{error}</p>}
                </div>

                <button
                  type="submit"
                  disabled={phase !== "idle"}
                  className="group w-full inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-ds-md font-semibold text-bg-base bg-gradient-to-r from-[#e8c65a] to-[#f2d67a] hover:from-[#f2d67a] hover:to-[#ffe89a] disabled:opacity-70 disabled:cursor-wait shadow-[0_0_30px_-8px_rgba(232,198,90,0.6)] active:scale-[0.98] transition-all"
                >
                  {busy || phase === "wrong" ? (
                    <>
                      <Loader2 size={17} className="animate-spin" />
                      {phase === "wrong" ? "Consulting the guardian…" : "Rubbing the lamp…"}
                    </>
                  ) : (
                    <>
                      <LogIn size={17} strokeWidth={2.5} />
                      Unlock the terminal
                      <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform" />
                    </>
                  )}
                </button>
              </form>
            )}

            <Link to="/" className="mt-6 text-ds-xs text-ink-dim hover:text-ink-secondary transition-colors">
              ← Back to the front page
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
