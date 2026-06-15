/**
 * SpireMark — Hand of Midas brand mark.
 *
 * Open rhombus body in off-white with vertical spires extending out the
 * top and bottom apexes. Small filled emerald rhombus at the geometric
 * center as the alpha gem.
 *
 * Two flavors:
 *   <SpireMark size={…} />          — static
 *   <SpireMark size={…} animate />  — SMIL animated, loops every 3.8s
 *
 * The viewBox is 64×64. Top spire tip = y=4, bottom tip = y=60.
 * Stroke widths are absolute (2px body / 1.4px spire) — they remain
 * proportionally crisp at every render size from 16px to hero.
 *
 * For sub-20px usage (favicons, tight chrome), prefer `compact`. It
 * drops the spires and renders just the rhombus + gem so the form
 * stays legible at favicon scale.
 */
import * as React from "react";

const TEXT = "#F1F3F6";
const E = "#10B981";
const E_HI = "#34D399";

interface SpireMarkProps {
  size?: number;
  animate?: boolean;
  /** Drop the spires (use under ~20px). Default false. */
  compact?: boolean;
  /** Optional override for the off-white stroke (e.g. for light surfaces). */
  bodyColor?: string;
  className?: string;
  style?: React.CSSProperties;
  "aria-label"?: string;
}

export function SpireMark({
  size = 64,
  animate = false,
  compact = false,
  bodyColor = TEXT,
  className,
  style,
  "aria-label": ariaLabel,
}: SpireMarkProps) {
  const role = ariaLabel ? "img" : undefined;
  const hidden = ariaLabel ? undefined : true;

  if (animate) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        role={role}
        aria-hidden={hidden}
        aria-label={ariaLabel}
        className={className}
        style={style}
      >
        {/* Body edges — staggered draw inward */}
        <path
          d="M16 32 L32 18"
          stroke={bodyColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray="22"
          strokeDashoffset="22"
        >
          <animate
            attributeName="stroke-dashoffset"
            values="22;0;0;22"
            keyTimes="0;0.3;0.85;1"
            dur="3.8s"
            repeatCount="indefinite"
          />
        </path>
        <path
          d="M48 32 L32 18"
          stroke={bodyColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray="22"
          strokeDashoffset="22"
        >
          <animate
            attributeName="stroke-dashoffset"
            values="22;0;0;22"
            keyTimes="0;0.3;0.85;1"
            dur="3.8s"
            begin="0.08s"
            repeatCount="indefinite"
          />
        </path>
        <path
          d="M16 32 L32 46"
          stroke={bodyColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray="22"
          strokeDashoffset="22"
        >
          <animate
            attributeName="stroke-dashoffset"
            values="22;0;0;22"
            keyTimes="0;0.3;0.85;1"
            dur="3.8s"
            begin="0.16s"
            repeatCount="indefinite"
          />
        </path>
        <path
          d="M48 32 L32 46"
          stroke={bodyColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray="22"
          strokeDashoffset="22"
        >
          <animate
            attributeName="stroke-dashoffset"
            values="22;0;0;22"
            keyTimes="0;0.3;0.85;1"
            dur="3.8s"
            begin="0.24s"
            repeatCount="indefinite"
          />
        </path>
        {/* Spires extend after body completes */}
        {!compact && (
          <>
            <path
              d="M32 18 L32 4"
              stroke={bodyColor}
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeDasharray="14"
              strokeDashoffset="14"
            >
              <animate
                attributeName="stroke-dashoffset"
                values="14;14;0;0;14"
                keyTimes="0;0.35;0.5;0.85;1"
                dur="3.8s"
                repeatCount="indefinite"
              />
            </path>
            <path
              d="M32 46 L32 60"
              stroke={bodyColor}
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeDasharray="14"
              strokeDashoffset="14"
            >
              <animate
                attributeName="stroke-dashoffset"
                values="14;14;0;0;14"
                keyTimes="0;0.35;0.5;0.85;1"
                dur="3.8s"
                repeatCount="indefinite"
              />
            </path>
          </>
        )}
        {/* Center alpha gem — appears after spires, with a brief glow */}
        <path d="M32 28 L36 32 L32 36 L28 32 Z" fill={E} opacity={0}>
          <animate
            attributeName="opacity"
            values="0;0;0;1;1;0"
            keyTimes="0;0.4;0.55;0.65;0.85;1"
            dur="3.8s"
            repeatCount="indefinite"
          />
        </path>
        <path d="M32 28 L36 32 L32 36 L28 32 Z" fill={E_HI} opacity={0}>
          <animate
            attributeName="opacity"
            values="0;0;0;0;0.5;0;0"
            keyTimes="0;0.4;0.55;0.65;0.7;0.85;1"
            dur="3.8s"
            repeatCount="indefinite"
          />
        </path>
      </svg>
    );
  }

  // Static
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      role={role}
      aria-hidden={hidden}
      aria-label={ariaLabel}
      className={className}
      style={style}
    >
      <path d="M16 32 L32 18" stroke={bodyColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M48 32 L32 18" stroke={bodyColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M16 32 L32 46" stroke={bodyColor} strokeWidth="2" strokeLinecap="round" />
      <path d="M48 32 L32 46" stroke={bodyColor} strokeWidth="2" strokeLinecap="round" />
      {!compact && (
        <>
          <path d="M32 18 L32 4" stroke={bodyColor} strokeWidth="1.4" strokeLinecap="round" />
          <path d="M32 46 L32 60" stroke={bodyColor} strokeWidth="1.4" strokeLinecap="round" />
        </>
      )}
      <path d="M32 28 L36 32 L32 36 L28 32 Z" fill={E} />
    </svg>
  );
}
