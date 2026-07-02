import { useEffect, useRef, useState } from "react";

/**
 * Price display that animates ONLY the digits that changed (per-character roll)
 * and shows a green ▲ when the price rose / red ▼ when it fell.
 */
export function PriceValue({
  value,
  digits = 2,
  className = "",
}: {
  value: number | null | undefined;
  digits?: number;
  className?: string;
}) {
  const prev = useRef<number | null>(value ?? null);
  const prevStr = useRef<string>("");
  const [dir, setDir] = useState<"up" | "down" | "flat">("flat");
  const [bump, setBump] = useState(0);

  const str = value == null ? "—" : value.toFixed(digits);

  useEffect(() => {
    if (value == null) return;
    const p = prev.current;
    if (p != null && value !== p) {
      setDir(value > p ? "up" : "down");
      setBump((b) => b + 1);
    }
    prev.current = value;
    prevStr.current = str;
  }, [value, str]);

  const dirColor = dir === "up" ? "text-bull" : dir === "down" ? "text-bear" : "text-ink-primary";
  const before = prevStr.current;

  return (
    <span className={`inline-flex items-baseline gap-1.5 ${className}`}>
      <span className="font-mono tabular-nums">
        {str.split("").map((ch, i) => {
          const changed = before && before[i] !== ch;
          return (
            <span
              key={`${i}-${ch}-${changed ? bump : "s"}`}
              className={`inline-block ${changed ? (dir === "down" ? "tick-down" : "tick-up") : ""}`}
            >
              {ch}
            </span>
          );
        })}
      </span>
      <span className={`text-[0.7em] ${dirColor}`}>
        {dir === "up" ? "▲" : dir === "down" ? "▼" : "·"}
      </span>
    </span>
  );
}
