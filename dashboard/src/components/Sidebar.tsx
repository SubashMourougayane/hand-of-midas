import { Link, useLocation } from "react-router-dom";
import {
  Radio,
  BarChart2,
  List,
  BookOpen,
  Layers,
  Activity,
} from "lucide-react";

const SECTIONS = [
  { to: "/live", label: "Live", icon: Radio },
  { to: "/trades", label: "Trades", icon: List },
  { to: "/journal", label: "Journal", icon: BookOpen },
  { to: "/signals", label: "Signals", icon: Activity },
  { to: "/backtest", label: "Backtest", icon: BarChart2 },
  { to: "/architecture", label: "Architecture", icon: Layers },
];

export function Sidebar() {
  const loc = useLocation();
  return (
    <nav
      aria-label="Sections"
      className="w-[200px] shrink-0 border-r border-line-subtle bg-bg-surface py-4 px-2.5 hidden md:flex md:flex-col"
    >
      <ul className="flex flex-col gap-0.5">
        {SECTIONS.map(({ to, label, icon: Icon }) => {
          const active = loc.pathname === to || loc.pathname.startsWith(to + "/");
          return (
            <li key={to} className="relative">
              {active && (
                <span
                  aria-hidden
                  className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-brass rounded-full"
                  style={{ boxShadow: "0 0 8px rgba(16,185,129,0.5)" }}
                />
              )}
              <Link
                to={to}
                aria-current={active ? "page" : undefined}
                className={`
                  flex items-center gap-3 h-10 pl-3 pr-2.5 rounded-ds-sm
                  text-[13.5px] font-medium
                  transition-colors duration-ds
                  ${
                    active
                      ? "bg-brass/10 text-brass-hi"
                      : "text-ink-secondary hover:text-ink-primary hover:bg-bg-elevated"
                  }
                `}
              >
                <Icon
                  size={15}
                  className={active ? "text-brass" : "text-ink-secondary"}
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
