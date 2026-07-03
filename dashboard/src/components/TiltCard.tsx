import * as React from "react";
import { useTilt } from "../lib/useTilt";

/**
 * A glass card that tilts in 3D toward the pointer (skill: perspective).
 * Must live inside a `.tilt-scene`. Children marked `.tilt-layer` lift toward
 * the viewer for parallax depth. A pointer-following glare rides on top.
 */
export function TiltCard({
  children,
  className = "",
  max = 9,
}: {
  children: React.ReactNode;
  className?: string;
  max?: number;
}) {
  const t = useTilt(max);
  return (
    <div
      ref={t.ref}
      onPointerMove={t.onPointerMove}
      onPointerLeave={t.onPointerLeave}
      className={`tilt-card relative ${className}`}
    >
      <span className="tilt-glare" aria-hidden />
      {children}
    </div>
  );
}
