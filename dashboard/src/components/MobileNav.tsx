import { Link, useLocation } from "react-router-dom";
import { Radio, BarChart2, List, BookOpen, Activity } from "lucide-react";

// Bottom tab bar for mobile (< md). The desktop Sidebar is hidden below md,
// so this is the primary nav on phones. Fixed, glass, thumb-reachable.
const TABS = [
  { to: "/live", label: "Live", icon: Radio },
  { to: "/trades", label: "Trades", icon: List },
  { to: "/signals", label: "Signals", icon: Activity },
  { to: "/journal", label: "Journal", icon: BookOpen },
  { to: "/backtest", label: "Backtest", icon: BarChart2 },
];

export function MobileNav() {
  const loc = useLocation();
  return (
    <nav
      aria-label="Sections"
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-glass-border bg-bg-base/80 backdrop-blur-xl pb-[env(safe-area-inset-bottom)]"
    >
      <ul className="flex items-stretch justify-around">
        {TABS.map(({ to, label, icon: Icon }) => {
          const active = loc.pathname === to || loc.pathname.startsWith(to + "/");
          return (
            <li key={to} className="flex-1">
              <Link
                to={to}
                aria-current={active ? "page" : undefined}
                className={`flex flex-col items-center gap-0.5 py-2.5 text-[10px] font-medium transition-colors ${
                  active ? "text-ink-primary" : "text-ink-muted"
                }`}
              >
                <Icon size={19} strokeWidth={active ? 2.4 : 1.8} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
