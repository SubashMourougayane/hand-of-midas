import * as React from "react";

const TEXT = "#F1F3F6";
const E = "#10B981";

export function SpireMark({
  size = 32,
  compact = false,
  bodyColor = TEXT,
  className,
  style,
  ariaLabel,
}: {
  size?: number;
  compact?: boolean;
  bodyColor?: string;
  className?: string;
  style?: React.CSSProperties;
  ariaLabel?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      role={ariaLabel ? "img" : undefined}
      aria-hidden={ariaLabel ? undefined : true}
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
