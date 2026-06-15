"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Radio, BarChart2, List, BookOpen, Layers, Settings } from "lucide-react";
import { cn } from "@/components/ui/cn";

const SECTIONS = [
  { href: "/live", label: "Live", icon: Radio },
  { href: "/trades", label: "Trades", icon: List },
  { href: "/journal", label: "Journal", icon: BookOpen },
  { href: "/backtest", label: "Backtest", icon: BarChart2 },
  { href: "/architecture", label: "Architecture", icon: Layers },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

export function SectionNav() {
  const path = usePathname();
  const searchParams = useSearchParams();
  const sys = searchParams.get("sys");
  const suffix = sys ? `?sys=${sys}` : "";

  return (
    <nav
      aria-label="Sections"
      className="hidden md:flex md:flex-col md:w-[200px] md:flex-shrink-0 md:border-r md:border-[var(--color-border)] md:bg-[var(--color-surface-1)] py-4 px-2.5"
    >
      <ul className="flex flex-col gap-0.5">
        {SECTIONS.map(({ href, label, icon: Icon }) => {
          const active = path === href || path.startsWith(href + "/");
          return (
            <li key={href} className="relative">
              {active ? (
                <span
                  aria-hidden
                  className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-[var(--color-brass)] rounded-full hom-fade-in"
                  style={{ boxShadow: "0 0 8px rgba(212,164,100,0.5)" }}
                />
              ) : null}
              <Link
                href={`${href}${suffix}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 h-10 pl-3 pr-2.5 rounded-[4px]",
                  "text-[13.5px] font-medium",
                  "transition-[color,background-color] duration-180 ease-out",
                  active
                    ? "bg-[var(--color-brass-tint)] text-[var(--color-brass-hi)]"
                    : "text-[var(--color-text-dim)] hover:text-[var(--color-text)] hover:bg-[var(--color-surface-2)]",
                )}
              >
                <Icon
                  size={15}
                  className={cn(
                    "transition-colors",
                    active ? "text-[var(--color-brass)]" : "text-[var(--color-text-dim)]",
                  )}
                />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function SectionNavMobile() {
  const path = usePathname();
  const searchParams = useSearchParams();
  const sys = searchParams.get("sys");
  const suffix = sys ? `?sys=${sys}` : "";

  return (
    <nav
      aria-label="Sections"
      className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-[var(--color-surface-1)] border-t border-[var(--color-border)] flex items-center justify-around px-1 h-[56px]"
    >
      {SECTIONS.slice(0, 5).map(({ href, label, icon: Icon }) => {
        const active = path === href || path.startsWith(href + "/");
        return (
          <Link
            key={href}
            href={`${href}${suffix}`}
            className={cn(
              "flex flex-col items-center justify-center gap-0.5 flex-1 h-full",
              "text-[10px] font-medium transition-colors",
              active ? "text-[var(--color-brass-hi)]" : "text-[var(--color-text-muted)]",
            )}
          >
            <Icon size={16} />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
