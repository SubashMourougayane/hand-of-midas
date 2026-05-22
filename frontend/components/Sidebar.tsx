"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart2, Radio, List, BookOpen, ChevronDown, ChevronRight, Layers, LogOut } from "lucide-react";
import { useState } from "react";
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
  const [oilOpen, setOilOpen] = useState(true);

  return (
    <aside className="w-[210px] min-h-screen border-r border-[var(--border)] p-4 flex flex-col bg-[var(--panel)]">
      <div className="text-[var(--green)] font-bold text-base mb-5 tracking-tight px-1">
        🤚 MIDAS
      </div>

      {/* GoldDigger Section */}
      <div className="mb-3">
        <button
          onClick={() => setGoldOpen(!goldOpen)}
          className="w-full flex items-center gap-2 px-1 py-2 text-sm font-bold transition-colors text-[#e8c300] hover:text-[#ffd700]"
        >
          {goldOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span>⛏️</span>
          <span>GOLDDIGGER</span>
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
    </aside>
  );
}
