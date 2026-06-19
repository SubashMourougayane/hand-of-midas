"use client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useInstrument, INSTRUMENTS, Instrument } from "@/lib/instrument";
import { cn } from "@/components/ui/cn";

// Macros retired 2026-06-19. See start-win.bat header for rationale.
const ORDER: Instrument[] = ["micro", "oil-micro"];

const SYSTEM_VAR: Record<Instrument, string> = {
  micro: "var(--color-sys-gold-micro)",
  "oil-micro": "var(--color-sys-oil-micro)",
};

const SHORT_LABEL: Record<Instrument, string> = {
  micro: "Gold Micro",
  "oil-micro": "Oil Micro",
};

export function SystemSwitcher() {
  const { instrument, setInstrument } = useInstrument();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Keyboard hotkeys: ⌘1..⌘4 swap systems
  useEffect(() => {
    const onHotkey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const idx = parseInt(e.key, 10) - 1;
      if (Number.isNaN(idx) || idx < 0 || idx >= ORDER.length) return;
      e.preventDefault();
      setInstrument(ORDER[idx]);
    };
    window.addEventListener("keydown", onHotkey);
    return () => window.removeEventListener("keydown", onHotkey);
  }, [setInstrument]);

  const current = INSTRUMENTS[instrument];
  const currentColor = SYSTEM_VAR[instrument];

  return (
    <>
      {/* Desktop: segmented control with brass-trim active pill */}
      <div
        role="tablist"
        aria-label="Active trading system"
        className="hidden lg:inline-flex items-center gap-0.5 p-0.5 rounded-[5px] bg-[var(--color-surface-1)] border border-[var(--color-border)]"
      >
        {ORDER.map((key, idx) => {
          const sys = INSTRUMENTS[key];
          const active = key === instrument;
          const color = SYSTEM_VAR[key];
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setInstrument(key)}
              title={`${SHORT_LABEL[key]} · ${sys.symbol} · ⌘${idx + 1}`}
              className={cn(
                "h-7 px-3 rounded-[3px] text-[11px] font-medium",
                "transition-[color,background-color,box-shadow] duration-200 ease-out",
                "flex items-center gap-2 whitespace-nowrap",
                active
                  ? "text-[var(--color-text)]"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text-dim)]",
              )}
              style={active ? {
                backgroundColor: `${color}1a`,
                boxShadow: `inset 0 0 0 1px ${color}80, 0 0 14px -4px ${color}40`,
              } : undefined}
            >
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full transition-transform",
                  active && "scale-110",
                )}
                style={{
                  backgroundColor: color,
                  boxShadow: active ? `0 0 6px ${color}` : undefined,
                }}
                aria-hidden
              />
              <span>{SHORT_LABEL[key]}</span>
            </button>
          );
        })}
      </div>

      {/* Mobile / tablet: dropdown */}
      <div className="lg:hidden relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="h-8 px-2.5 rounded-[6px] flex items-center gap-2 text-[12px] font-medium text-[var(--color-text)] bg-[var(--color-surface-1)] border border-[var(--color-border)] hover:border-[var(--color-border-hi)] transition-colors"
          aria-haspopup="listbox"
          aria-expanded={open}
        >
          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: currentColor }} aria-hidden />
          <span className="whitespace-nowrap">{SHORT_LABEL[instrument]}</span>
          <ChevronDown size={12} className="text-[var(--color-text-muted)]" />
        </button>

        {open ? (
          <div
            role="listbox"
            className="absolute top-full mt-1 right-0 min-w-[160px] z-50 rounded-[6px] bg-[var(--color-surface-2)] border border-[var(--color-border-hi)] shadow-xl overflow-hidden"
          >
            {ORDER.map((key) => {
              const sys = INSTRUMENTS[key];
              const active = key === instrument;
              const color = SYSTEM_VAR[key];
              return (
                <button
                  key={key}
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => { setInstrument(key); setOpen(false); }}
                  className={cn(
                    "w-full px-3 py-2 flex items-center justify-between gap-3 text-[12px] transition-colors",
                    active
                      ? "text-[var(--color-text)] bg-[var(--color-surface-3)]"
                      : "text-[var(--color-text-dim)] hover:bg-[var(--color-surface-3)]",
                  )}
                >
                  <span className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} aria-hidden />
                    <span>{SHORT_LABEL[key]}</span>
                  </span>
                  <span className="num text-[11.5px] text-[var(--color-text-dim)]">{sys.symbol}</span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </>
  );
}
