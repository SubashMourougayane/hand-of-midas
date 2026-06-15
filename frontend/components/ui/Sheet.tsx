"use client";
import { ReactNode, useEffect } from "react";
import { cn } from "./cn";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  side?: "right" | "left" | "bottom";
  width?: number;
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}

const SIDE: Record<NonNullable<SheetProps["side"]>, string> = {
  right: "top-0 right-0 h-full",
  left: "top-0 left-0 h-full",
  bottom: "left-0 right-0 bottom-0 max-h-[85vh]",
};

export function Sheet({
  open,
  onClose,
  side = "right",
  width = 480,
  title,
  children,
  className,
}: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  const dimensionStyle = side === "bottom" ? {} : { width };

  return (
    <div className="fixed inset-0 z-[1000] flex" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px] animate-[fade-in_120ms_ease-out]"
        onClick={onClose}
      />
      <aside
        style={dimensionStyle}
        className={cn(
          "absolute bg-[var(--color-surface-1)] border-[var(--color-border)] shadow-2xl",
          "flex flex-col",
          side === "right" && "border-l rounded-l-[8px] animate-[slide-in-right_180ms_ease-out]",
          side === "left" && "border-r rounded-r-[8px] animate-[slide-in-left_180ms_ease-out]",
          side === "bottom" && "border-t rounded-t-[12px] animate-[slide-in-bottom_200ms_ease-out]",
          SIDE[side],
          className,
        )}
      >
        {title != null ? (
          <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[var(--color-border)]">
            <span className="text-[13px] font-semibold text-[var(--color-text)]">{title}</span>
            <button
              onClick={onClose}
              aria-label="Close"
              className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors text-[18px] leading-none"
            >
              ×
            </button>
          </header>
        ) : null}
        <div className="flex-1 overflow-auto">{children}</div>
      </aside>
      <style jsx>{`
        @keyframes slide-in-right {
          from { transform: translateX(100%); opacity: 0.6; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slide-in-left {
          from { transform: translateX(-100%); opacity: 0.6; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slide-in-bottom {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
        @keyframes fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
