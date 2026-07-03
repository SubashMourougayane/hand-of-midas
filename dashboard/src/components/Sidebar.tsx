import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Radio,
  BarChart2,
  List,
  BookOpen,
  Layers,
  Activity,
  Home,
  LogOut,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui/tooltip";
import { useAuth } from "../lib/auth";

const SECTIONS = [
  { to: "/", label: "Home", icon: Home },
  { to: "/live", label: "Live", icon: Radio },
  { to: "/trades", label: "Trades", icon: List },
  { to: "/journal", label: "Journal", icon: BookOpen },
  { to: "/signals", label: "Signals", icon: Activity },
  { to: "/backtest", label: "Backtest", icon: BarChart2 },
  { to: "/architecture", label: "Architecture", icon: Layers },
];

export function Sidebar({ collapsed = false }: { collapsed?: boolean }) {
  const loc = useLocation();
  const nav = useNavigate();
  const { logout } = useAuth();
  const doLogout = () => {
    logout();
    nav("/login", { replace: true });
  };
  return (
    <TooltipProvider delayDuration={0}>
      <nav
        aria-label="Sections"
        className={`shrink-0 border-r border-glass-border bg-glass-subtle backdrop-blur-xl py-4 hidden md:flex md:flex-col transition-[width] duration-200 ${
          collapsed ? "w-[64px] px-2" : "w-[200px] px-2.5"
        }`}
      >
        <ul className="flex flex-col gap-0.5">
          {SECTIONS.map(({ to, label, icon: Icon }) => {
            const active =
              to === "/"
                ? loc.pathname === "/"
                : loc.pathname === to || loc.pathname.startsWith(to + "/");
            const link = (
              <Link
                to={to}
                aria-current={active ? "page" : undefined}
                aria-label={label}
                className={`
                  flex items-center h-10 rounded-ds-sm text-[13.5px] font-medium
                  transition-colors duration-ds
                  ${collapsed ? "justify-center px-0" : "gap-3 pl-3 pr-2.5"}
                  ${
                    active
                      ? "glass-strong text-ink-primary"
                      : "text-ink-secondary hover:text-ink-primary hover:bg-glass"
                  }
                `}
              >
                <Icon size={16} className={active ? "text-ink-primary" : "text-ink-muted"} />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
            return (
              <li key={to} className="relative">
                {active && (
                  <span
                    aria-hidden
                    className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-brass-hi rounded-full"
                    style={{ boxShadow: "0 0 10px rgba(255,255,255,0.5)" }}
                  />
                )}
                {collapsed ? (
                  <Tooltip>
                    <TooltipTrigger asChild>{link}</TooltipTrigger>
                    <TooltipContent side="right">{label}</TooltipContent>
                  </Tooltip>
                ) : (
                  link
                )}
              </li>
            );
          })}
        </ul>

        {/* Logout pinned to the bottom of the rail. */}
        <div className="mt-auto pt-2">
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={doLogout}
                  aria-label="Log out"
                  className="w-full flex items-center justify-center h-10 rounded-ds-sm text-ink-muted hover:text-bear hover:bg-glass transition-colors"
                >
                  <LogOut size={16} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">Log out</TooltipContent>
            </Tooltip>
          ) : (
            <button
              onClick={doLogout}
              className="w-full flex items-center gap-3 h-10 pl-3 pr-2.5 rounded-ds-sm text-[13.5px] font-medium text-ink-muted hover:text-bear hover:bg-glass transition-colors"
            >
              <LogOut size={16} />
              <span>Log out</span>
            </button>
          )}
        </div>
      </nav>
    </TooltipProvider>
  );
}
