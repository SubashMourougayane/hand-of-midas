import { useEffect, useRef, useState } from "react";

/**
 * Wraps a live-updating value and plays a brief directional slide (up when the
 * numeric value rose, down when it fell) each time it changes. Purely visual —
 * renders the already-formatted string you pass in.
 */
export function AnimatedNumber({
  value,
  numeric,
  className = "",
}: {
  /** formatted display string, e.g. "+$305.22" */
  value: React.ReactNode;
  /** raw numeric used only to pick slide direction */
  numeric?: number | null;
  className?: string;
}) {
  const prev = useRef<number | null>(numeric ?? null);
  const [dir, setDir] = useState<"up" | "down" | null>(null);
  const [key, setKey] = useState(0);

  useEffect(() => {
    if (numeric == null) return;
    const p = prev.current;
    if (p != null && numeric !== p) {
      setDir(numeric > p ? "up" : "down");
      setKey((k) => k + 1);
    }
    prev.current = numeric;
  }, [numeric]);

  return (
    <span className="inline-block overflow-hidden align-baseline">
      <span
        key={key}
        className={`inline-block ${dir === "up" ? "tick-up" : dir === "down" ? "tick-down" : ""} ${className}`}
      >
        {value}
      </span>
    </span>
  );
}
