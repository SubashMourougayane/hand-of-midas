"use client";
import Link from "next/link";
import { SystemSwitcher } from "./SystemSwitcher";
import { UserMenu } from "./UserMenu";
import { StatusDot } from "@/components/ui/StatusDot";

export function TopBar() {
  return (
    <header className="h-[56px] flex-shrink-0 sticky top-0 z-30 flex items-center gap-3 px-3 md:px-4 border-b border-[var(--color-border)] bg-[var(--color-bg)]/95 backdrop-blur-sm">
      <Link
        href="/live"
        className="flex items-center gap-2 text-[var(--color-text)] font-semibold tracking-tight"
      >
        <span className="text-[18px]" aria-hidden>🤚</span>
        <span className="hidden sm:inline text-[13px]">Hand of Midas</span>
      </Link>

      <div className="hidden md:flex items-center gap-1.5 text-[10px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">
        <StatusDot tone="win" pulse size={6} />
        <span>Live</span>
      </div>

      <div className="flex-1 flex items-center justify-center">
        <SystemSwitcher />
      </div>

      <div className="flex items-center gap-2">
        <UserMenu />
      </div>
    </header>
  );
}
