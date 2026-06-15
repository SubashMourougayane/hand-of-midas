"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { LogOut, Settings as SettingsIcon, User } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/components/ui/cn";

export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const initial = user?.email?.[0]?.toUpperCase() ?? user?.name?.[0]?.toUpperCase() ?? "U";

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="w-8 h-8 rounded-full bg-[var(--color-surface-2)] border border-[var(--color-border)] hover:border-[var(--color-border-hi)] flex items-center justify-center text-[12px] font-semibold text-[var(--color-text)] transition-colors"
      >
        {initial}
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute top-full mt-1 right-0 min-w-[200px] z-50 rounded-[6px] bg-[var(--color-surface-2)] border border-[var(--color-border-hi)] shadow-xl overflow-hidden"
        >
          <div className="px-3 py-2 border-b border-[var(--color-border)]">
            <p className="text-[12px] text-[var(--color-text)] truncate">{user?.email ?? "Signed in"}</p>
          </div>
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className={cn(
              "flex items-center gap-2 px-3 py-2 text-[12px] text-[var(--color-text-dim)]",
              "hover:bg-[var(--color-surface-3)] hover:text-[var(--color-text)] transition-colors",
            )}
          >
            <SettingsIcon size={13} />
            <span>Settings</span>
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => { setOpen(false); logout(); }}
            className={cn(
              "w-full flex items-center gap-2 px-3 py-2 text-[12px] text-[var(--color-text-dim)]",
              "hover:bg-[var(--color-surface-3)] hover:text-[var(--color-loss)] transition-colors",
            )}
          >
            <LogOut size={13} />
            <span>Log out</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
