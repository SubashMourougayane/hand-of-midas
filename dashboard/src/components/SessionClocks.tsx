// Four market-session clocks for the footer. Each shows a flag, the local
// time in that zone, and an open/closed dot for FX session hours.
// Session windows are in UTC (approx, no DST nuance — good enough for a glance).
const SESSIONS = [
  { flag: "🇯🇵", name: "Asia", tz: "Asia/Tokyo", openUtc: [0, 9] as [number, number] },
  { flag: "🇬🇧", name: "London", tz: "Europe/London", openUtc: [7, 16] as [number, number] },
  { flag: "🇺🇸", name: "New York", tz: "America/New_York", openUtc: [13, 22] as [number, number] },
  { flag: "🇮🇳", name: "India", tz: "Asia/Kolkata", openUtc: null }, // reference only
];

function timeIn(tz: string, d: Date): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(d);
  } catch {
    return "--:--";
  }
}

function isOpen(openUtc: [number, number] | null, d: Date): boolean {
  if (!openUtc) return false;
  const day = d.getUTCDay(); // 0 Sun, 6 Sat — FX shut on weekend
  if (day === 0 || day === 6) return false;
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  const [lo, hi] = openUtc;
  return h >= lo && h < hi;
}

export function SessionClocks({ now }: { now: number }) {
  const d = new Date(now);
  return (
    <div className="hidden lg:flex items-center gap-4">
      {SESSIONS.map((s) => {
        const open = isOpen(s.openUtc, d);
        return (
          <span key={s.name} className="inline-flex items-center gap-1.5" title={`${s.name} · ${s.tz}`}>
            <span className="text-[13px] leading-none">{s.flag}</span>
            {s.openUtc && (
              <span
                className={`w-1.5 h-1.5 rounded-full ${open ? "bg-bull ds-dot text-bull" : "bg-ink-dim"}`}
              />
            )}
            <span className="font-mono text-ink-secondary tabular-nums">{timeIn(s.tz, d)}</span>
            <span className="text-ink-dim uppercase tracking-wide hidden xl:inline">{s.name}</span>
          </span>
        );
      })}
    </div>
  );
}
