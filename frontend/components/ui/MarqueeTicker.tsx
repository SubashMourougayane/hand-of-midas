"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

interface MarqueeTickerProps {
  children: ReactNode;
  /** Duration per full loop in seconds (lower = faster). Default 60s. */
  speed?: number;
  className?: string;
}

/**
 * Infinite-loop horizontal marquee. Renders children twice and translates
 * the wrapper -50% to give a seamless wrap. Pauses on hover.
 *
 * Use case: live price ticker in TopBar, signal feed across the bottom of
 * the landing page, etc. Honors prefers-reduced-motion: animation stops
 * via globals.css media query.
 */
export function MarqueeTicker({ children, speed = 60, className }: MarqueeTickerProps) {
  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "[mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]",
        className,
      )}
    >
      <div
        className="flex gap-8 whitespace-nowrap will-change-transform hover:[animation-play-state:paused]"
        style={{
          animation: `hom-marquee ${speed}s linear infinite`,
          width: "max-content",
        }}
      >
        <div className="flex gap-8 items-center">{children}</div>
        <div className="flex gap-8 items-center" aria-hidden>{children}</div>
      </div>
    </div>
  );
}
