"use client";
import { useEffect, useRef, useState } from "react";

interface CountUpProps {
  /** Target numeric value to animate to. */
  value: number;
  /** Duration in milliseconds. */
  duration?: number;
  /** Number of decimals to render. */
  decimals?: number;
  /** Prefix (e.g. "$" or "+$"). Sign is NOT auto-added — caller controls. */
  prefix?: string;
  /** Suffix (e.g. "%", "R"). */
  suffix?: string;
  /** Group thousands using locale formatting. */
  locale?: string;
  className?: string;
}

/**
 * Lightweight count-up tween. Uses requestAnimationFrame, easeOutCubic.
 * Re-runs whenever `value` changes. Honors prefers-reduced-motion: snaps
 * to the final value immediately.
 */
export function CountUp({
  value,
  duration = 600,
  decimals = 0,
  prefix = "",
  suffix = "",
  locale = "en-GB",
  className,
}: CountUpProps) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      setDisplay(value);
      return;
    }
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
    const tick = (t: number) => {
      const elapsed = t - start;
      const p = Math.min(1, elapsed / duration);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(from + (to - from) * eased);
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplay(to);
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      fromRef.current = value;
    };
  }, [value, duration]);

  const formatted = display.toLocaleString(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return <span className={className}>{prefix}{formatted}{suffix}</span>;
}
