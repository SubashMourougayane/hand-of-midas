"use client";
import Link from "next/link";
import { SystemSwitcher } from "./SystemSwitcher";
import { UserMenu } from "./UserMenu";
import { StatusDot } from "@/components/ui/StatusDot";
import { useInstrument, INSTRUMENTS } from "@/lib/instrument";

const SHORT_LABEL: Record<string, string> = {
  gold: "Gold Macro",
  micro: "Gold Micro",
  oil: "Oil Macro",
  "oil-micro": "Oil Micro",
};

export function TopBar() {
  const { instrument } = useInstrument();
  const sys = INSTRUMENTS[instrument];
  return (
    <header className="h-[60px] flex-shrink-0 sticky top-0 z-30 flex items-center gap-4 px-5 md:px-6 border-b border-[var(--color-border)] bg-[var(--color-bg)]/95 backdrop-blur-md">
      {/* Brand mark — serif wordmark with brass diamond */}
      <Link
        href="/live"
        className="flex items-center gap-3 text-[var(--color-text)] tracking-tight group"
      >
        <span
          className="inline-block w-3 h-3 rotate-45 bg-[var(--color-brass)] group-hover:bg-[var(--color-brass-hi)] transition-colors"
          style={{ boxShadow: "0 0 12px rgba(16,185,129,0.4)" }}
          aria-hidden
        />
        <span className="display text-[19px] leading-none italic hidden sm:inline">
          Hand of Midas
        </span>
      </Link>

      {/* Live indicator — pulses when scheduler is up */}
      <div className="hidden md:flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)] pl-3 ml-1 border-l border-[var(--color-border)]">
        <StatusDot tone="win" pulse size={6} />
        <span>Live</span>
      </div>

      <div className="flex-1 flex items-center justify-center">
        <SystemSwitcher />
      </div>

      <div className="flex items-center gap-3">
        <span className="hidden md:inline-flex items-center gap-1.5 text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)]">
          <span className="text-[var(--color-text)]">{sys.symbol}</span>
          <span className="display italic text-[var(--color-brass)]">·</span>
          <span>{SHORT_LABEL[instrument] ?? "—"}</span>
        </span>
        <UserMenu />
      </div>
    </header>
  );
}
