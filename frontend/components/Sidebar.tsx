"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart2, Radio, List, BookOpen, ChevronDown, ChevronRight, Layers, LogOut, Menu, X, FileBarChart } from "lucide-react";
import { useState, useEffect } from "react";
import { useInstrument, INSTRUMENTS, Instrument } from "@/lib/instrument";
import { useAuth } from "@/contexts/AuthContext";

const PAGES = [
  { href: "/live", label: "Live", icon: Radio },
  { href: "/backtest", label: "Backtest", icon: BarChart2 },
  { href: "/trades", label: "Trades", icon: List },
  { href: "/journal", label: "Journal", icon: BookOpen },
];

export default function Sidebar() {
  const path = usePathname();
  const { instrument, setInstrument } = useInstrument();
  const { logout } = useAuth();
  const [goldOpen, setGoldOpen] = useState(true);
  const [microOpen, setMicroOpen] = useState(true);
  const [oilOpen, setOilOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close sidebar on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [path]);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  const sidebarContent = (
    <>
      <div className="text-[var(--green)] font-bold text-base mb-5 tracking-tight px-1">
        🤚 MIDAS
      </div>

      {/* Gold Macro Section */}
      <div className="mb-3">
        <button
          onClick={() => setGoldOpen(!goldOpen)}
          className="w-full flex items-center gap-2 px-1 py-2 text-sm font-bold transition-colors text-[#e8c300] hover:text-[#ffd700]"
        >
          {goldOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>⛏️</span>
          <span>GOLD MACRO</span>
        </button>
        {goldOpen && (
          <div className="ml-5 border-l border-[var(--border)] pl-3 mt-1">
            {PAGES.map((item) => {
              const active = path === item.href && instrument === "gold";
              return (
                <Link key={`gold-${item.href}`} href={item.href}
                  onClick={() => setInstrument("gold")}
                  className={`flex items-center gap-2.5 px-2 py-2 text-xs transition-colors ${
                    active ? "text-[#e8c300] bg-[#e8c30015]" : "text-[var(--text-dim)] hover:text-[var(--text)]"
                  }`}>
                  <item.icon size={14} />
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* Gold Micro Section */}
      <div className="mb-3">
        <button
          onClick={() => setMicroOpen(!microOpen)}
          className="w-full flex items-center gap-2 px-1 py-2 text-sm font-bold transition-colors text-[#ff8c00] hover:text-[#ffa040]"
        >
          {microOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>⚡</span>
          <span>GOLD MICRO</span>
        </button>
        {microOpen && (
          <div className="ml-5 border-l border-[var(--border)] pl-3 mt-1">
            {PAGES.map((item) => {
              const active = path === item.href && instrument === "micro";
              return (
                <Link key={`micro-${item.href}`} href={item.href}
                  onClick={() => setInstrument("micro")}
                  className={`flex items-center gap-2.5 px-2 py-2 text-xs transition-colors ${
                    active ? "text-[#ff8c00] bg-[#ff8c0015]" : "text-[var(--text-dim)] hover:text-[var(--text)]"
                  }`}>
                  <item.icon size={14} />
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* OilMiner Section */}
      <div className="mb-3">
        <button
          onClick={() => setOilOpen(!oilOpen)}
          className="w-full flex items-center gap-2 px-1 py-2 text-sm font-bold transition-colors text-[#4fc3f7] hover:text-[#81d4fa]"
        >
          {oilOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>🛢️</span>
          <span>OILMINER</span>
        </button>
        {oilOpen && (
          <div className="ml-5 border-l border-[var(--border)] pl-3 mt-1">
            {PAGES.map((item) => {
              const active = path === item.href && instrument === "oil";
              return (
                <Link key={`oil-${item.href}`} href={item.href}
                  onClick={() => setInstrument("oil")}
                  className={`flex items-center gap-2.5 px-2 py-2 text-xs transition-colors ${
                    active ? "text-[#4fc3f7] bg-[#4fc3f715]" : "text-[var(--text-dim)] hover:text-[var(--text)]"
                  }`}>
                  <item.icon size={14} />
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* Shared pages */}
      <div className="mb-3 mt-2 pt-2 border-t border-[var(--border)]">
        <Link href="/architecture"
          className={`flex items-center gap-2.5 px-2 py-2 text-xs transition-colors ${
            path === "/architecture" ? "text-[var(--green)] bg-[#00e87b15]" : "text-[var(--text-dim)] hover:text-[var(--text)]"
          }`}>
          <Layers size={14} />
          Architecture
        </Link>
        <a href="/midas-report.html" target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-2.5 px-2 py-2 text-xs transition-colors text-[var(--text-dim)] hover:text-[var(--amber)]">
          <FileBarChart size={14} />
          Midas Report
        </a>
      </div>

      {/* Active + Logout */}
      <div className="mt-auto pt-4 border-t border-[var(--border)] px-1">
        <div className="text-[9px] text-[var(--text-dim)] uppercase tracking-wider">Active</div>
        <div className="text-xs font-bold mt-1" style={{ color: INSTRUMENTS[instrument].color }}>
          {INSTRUMENTS[instrument].symbol}
        </div>
        <button
          onClick={logout}
          className="flex items-center gap-2 mt-3 px-2 py-1.5 text-xs text-[var(--text-dim)] hover:text-[var(--red)] transition-colors w-full"
        >
          <LogOut size={12} />
          Logout
        </button>
      </div>
    </>
  );

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-3 left-3 z-50 p-2 bg-[var(--panel)] border border-[var(--border)] text-[var(--text)]"
        aria-label="Open menu"
      >
        <Menu size={20} />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/60 z-50"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile slide-out sidebar */}
      <aside
        className={`md:hidden fixed top-0 left-0 h-full w-[240px] z-50 p-4 flex flex-col bg-[var(--panel)] border-r border-[var(--border)] transform transition-transform duration-200 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute top-3 right-3 p-1 text-[var(--text-dim)] hover:text-[var(--text)]"
          aria-label="Close menu"
        >
          <X size={18} />
        </button>
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-[210px] min-h-screen border-r border-[var(--border)] p-4 flex-col bg-[var(--panel)]">
        {sidebarContent}
      </aside>
    </>
  );
}
