import * as React from "react";

/**
 * Hand of Midas brand mark — the approved "Coin Lockup" (coinlock):
 * a steel diamond spire cradling a gilded core, set in a soft gold coin.
 *
 * Philosophy: the coin = the account; the steel spire = disciplined edge;
 * the gold core = refined value (base → gold, the Midas touch).
 *
 * Variants:
 *   "coin" (default) — full lockup with the coin backdrop (nav, login, favicon)
 *   "bare"           — mark only, transparent (inline in text, tight spaces)
 *
 * Animation (opt-in via `animate`): a slow gold shimmer sweeps the core and a
 * faint aura breathes — calm, premium, never distracting. Respects
 * prefers-reduced-motion (CSS handles the disable). `spinOnHover` rotates the
 * coin a touch on hover when the mark sits inside a `group`.
 */
export function MidasMark({
  size = 32,
  variant = "coin",
  animate = false,
  spinOnHover = false,
  className,
  style,
  ariaLabel = "Hand of Midas",
}: {
  size?: number;
  variant?: "coin" | "bare";
  animate?: boolean;
  spinOnHover?: boolean;
  className?: string;
  style?: React.CSSProperties;
  ariaLabel?: string;
}) {
  // Unique gradient ids so multiple marks on one page don't collide.
  const uid = React.useId().replace(/:/g, "");
  const g = (n: string) => `${n}_${uid}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      role="img"
      aria-label={ariaLabel}
      className={`${animate ? "midas-mark-animated" : ""} ${
        spinOnHover ? "transition-transform duration-500 group-hover:rotate-[10deg]" : ""
      } ${className ?? ""}`}
      style={style}
    >
      <defs>
        <linearGradient id={g("steel")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#c8cfda" />
        </linearGradient>
        <linearGradient id={g("gold")} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f4e4a8" />
          <stop offset="0.5" stopColor="#e8c65a" />
          <stop offset="1" stopColor="#b8901f" />
        </linearGradient>
        <linearGradient id={g("coin")} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3a2f10" />
          <stop offset="1" stopColor="#1a1608" />
        </linearGradient>
        <radialGradient id={g("glow")} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="rgba(232,198,90,0.55)" />
          <stop offset="1" stopColor="rgba(232,198,90,0)" />
        </radialGradient>
        {/* Moving shimmer band swept across the gold core when animated. */}
        <linearGradient id={g("shim")} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="rgba(255,255,255,0)" />
          <stop offset="0.5" stopColor="rgba(255,255,255,0.85)" />
          <stop offset="1" stopColor="rgba(255,255,255,0)" />
        </linearGradient>
        <clipPath id={g("core")}>
          <path d="M60 52 L68 60 L60 68 L52 60 Z" />
        </clipPath>
      </defs>

      {variant === "coin" && (
        <>
          <rect
            x="10"
            y="10"
            width="100"
            height="100"
            rx="26"
            fill={`url(#${g("coin")})`}
            stroke="rgba(90,74,24,0.55)"
            strokeWidth="2"
          />
          <circle
            cx="60"
            cy="58"
            r="30"
            fill={`url(#${g("glow")})`}
            className={animate ? "midas-aura" : ""}
          />
        </>
      )}

      {/* steel diamond frame */}
      <path
        d="M60 34 L86 60 L60 86 L34 60 Z"
        fill="none"
        stroke={`url(#${g("steel")})`}
        strokeWidth="5"
        strokeLinejoin="round"
      />

      {/* gilded core */}
      <path d="M60 52 L68 60 L60 68 L52 60 Z" fill={`url(#${g("gold")})`} />

      {/* shimmer sweep, clipped to the core */}
      {animate && (
        <g clipPath={`url(#${g("core")})`}>
          <rect
            className="midas-shimmer"
            x="-24"
            y="48"
            width="24"
            height="24"
            fill={`url(#${g("shim")})`}
            opacity="0.9"
          />
        </g>
      )}
    </svg>
  );
}
