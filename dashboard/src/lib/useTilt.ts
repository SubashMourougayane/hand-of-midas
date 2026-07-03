import { useRef, useCallback } from "react";

/**
 * Pointer-tracked 3D tilt (skill: perspective). Attach the returned handlers to
 * a `.tilt-card` inside a `.tilt-scene`. The card rotates toward the pointer and
 * feeds a radial glare position via CSS vars — no per-frame React re-render.
 *
 * Honours reduced-motion at the CSS layer (the .tilt-card rule is neutralised),
 * so the handlers are harmless no-ops visually when motion is disabled.
 */
export function useTilt(max = 9) {
  const ref = useRef<HTMLDivElement | null>(null);

  const onMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const el = ref.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width; // 0..1
      const py = (e.clientY - r.top) / r.height; // 0..1
      const ry = (px - 0.5) * (max * 2); // rotateY: left/right
      const rx = (0.5 - py) * (max * 2); // rotateX: up/down
      el.style.setProperty("--ry", `${ry.toFixed(2)}deg`);
      el.style.setProperty("--rx", `${rx.toFixed(2)}deg`);
      el.style.setProperty("--mx", `${(px * 100).toFixed(1)}%`);
      el.style.setProperty("--my", `${(py * 100).toFixed(1)}%`);
      el.classList.add("is-live");
    },
    [max]
  );

  const onLeave = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.classList.remove("is-live");
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  }, []);

  return { ref, onPointerMove: onMove, onPointerLeave: onLeave };
}
