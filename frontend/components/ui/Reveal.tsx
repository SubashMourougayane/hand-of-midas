"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

interface RevealProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  /** "up" = stagger-up (default), "fade" = pure opacity */
  mode?: "up" | "fade";
}

/**
 * Plain CSS-keyframe reveal wrapper. Lighter than Framer Motion.
 * Use as `<Reveal delay={120}>...</Reveal>` for one-off entries, or wrap a
 * grid in <div className="hom-stagger-children"> with each child receiving
 * `.hom-stagger` to stagger them automatically (delays handled in globals.css).
 */
export function Reveal({ children, delay = 0, mode = "up", className }: RevealProps) {
  const animClass = mode === "up" ? "hom-stagger" : "hom-fade-in";
  const style = delay ? { animationDelay: `${delay}ms` } : undefined;
  return (
    <div className={cn(animClass, className)} style={style}>
      {children}
    </div>
  );
}
