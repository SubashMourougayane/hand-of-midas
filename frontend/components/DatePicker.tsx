"use client";
import { useState, useRef, useEffect } from "react";
import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";

interface DatePickerProps {
  value: string; // YYYY-MM-DD
  onChange: (date: string) => void;
  label?: string;
}

export default function DatePicker({ value, onChange, label }: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const [viewYear, setViewYear] = useState(0);
  const [viewMonth, setViewMonth] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (value) {
      const d = new Date(value);
      setViewYear(d.getFullYear());
      setViewMonth(d.getMonth());
    }
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selectedDate = value ? new Date(value) : null;

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(viewYear - 1); }
    else setViewMonth(viewMonth - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(viewYear + 1); }
    else setViewMonth(viewMonth + 1);
  };

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const firstDow = new Date(viewYear, viewMonth, 1).getDay();
  const startOffset = firstDow === 0 ? 6 : firstDow - 1;

  const monthNames = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];

  const selectDay = (day: number) => {
    const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    onChange(dateStr);
    setOpen(false);
  };

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  return (
    <div className="relative" ref={ref}>
      {label && <label className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider block mb-1">{label}</label>}
      <button
        onClick={() => { setOpen(!open); if (!open && value) { const d = new Date(value); setViewYear(d.getFullYear()); setViewMonth(d.getMonth()); } }}
        className="flex items-center gap-2 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] text-xs px-2.5 py-1.5 w-[150px] hover:border-[var(--green)] transition-colors"
      >
        <Calendar size={11} className="text-[var(--text-dim)]" />
        <span>{value || "Select date"}</span>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 w-[320px] bg-[var(--panel)] border border-[var(--border)] shadow-2xl shadow-black/50 p-4">
          {/* Month/Year header */}
          <div className="flex items-center justify-between mb-4">
            <button onClick={prevMonth} className="w-6 h-6 flex items-center justify-center text-[var(--text-dim)] hover:text-[var(--text)]">
              <ChevronLeft size={14} />
            </button>
            <span className="text-xs font-bold tracking-widest text-[var(--text)]">
              {monthNames[viewMonth]} {viewYear}
            </span>
            <button onClick={nextMonth} className="w-6 h-6 flex items-center justify-center text-[var(--text-dim)] hover:text-[var(--text)]">
              <ChevronRight size={14} />
            </button>
          </div>

          {/* Day headers */}
          <div className="grid grid-cols-7 gap-0 mb-1">
            {["MO", "TU", "WE", "TH", "FR", "SA", "SU"].map((d) => (
              <div key={d} className="text-center text-[9px] font-semibold tracking-wider text-[var(--text-dim)] py-1">
                {d}
              </div>
            ))}
          </div>

          {/* Day grid */}
          <div className="grid grid-cols-7 gap-[2px]">
            {/* Offset */}
            {Array.from({ length: startOffset }).map((_, i) => (
              <div key={`off-${i}`} className="aspect-square" />
            ))}

            {/* Days */}
            {Array.from({ length: daysInMonth }).map((_, i) => {
              const day = i + 1;
              const dateStr = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
              const dt = new Date(viewYear, viewMonth, day);
              const dow = dt.getDay();
              const isWeekend = dow === 0 || dow === 6;
              const isSelected = dateStr === value;
              const isToday = dateStr === todayStr;

              return (
                <button
                  key={day}
                  onClick={() => selectDay(day)}
                  className={`aspect-square flex items-center justify-center text-xs font-semibold transition-all
                    ${isSelected
                      ? "bg-[var(--green)] text-[var(--bg)]"
                      : isToday
                        ? "border border-[var(--blue)] text-[var(--blue)]"
                        : isWeekend
                          ? "text-[var(--text-dim)] opacity-40"
                          : "text-[var(--text)] hover:bg-[#1a2030]"
                    }
                  `}
                >
                  {day}
                </button>
              );
            })}
          </div>

          {/* Legend */}
          <div className="flex items-center gap-4 mt-3 pt-2 border-t border-[var(--border)]">
            <div className="flex items-center gap-1.5 text-[8px] text-[var(--text-dim)]">
              <span className="w-2.5 h-2.5 bg-[var(--green)]" /> SELECTED
            </div>
            <div className="flex items-center gap-1.5 text-[8px] text-[var(--text-dim)]">
              <span className="w-2.5 h-2.5 border border-[var(--blue)]" /> TODAY
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
