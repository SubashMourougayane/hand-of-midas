// Four market-session clocks for the footer. Each shows a flag, the local
// time in that zone, and an open/closed dot for FX session hours.
// Session windows are in UTC (approx, no DST nuance — good enough for a glance).
const SESSIONS = [
  { flag: "🇦🇺", name: "Sydney", tz: "Australia/Sydney", openUtc: [21, 6] as [number, number] }, // wraps midnight UTC
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

// The FX week runs Sun 21:00 UTC (Sydney open) → Fri 22:00 UTC (NY close).
// Saturday is fully shut; Sunday before 21:00 and Friday after 22:00 are shut.
function fxWeekOpen(d: Date): boolean {
  const day = d.getUTCDay(); // 0 Sun … 6 Sat
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  if (day === 6) return false;           // Saturday — shut all day
  if (day === 0) return h >= 21;         // Sunday — opens at 21:00 UTC (Sydney)
  if (day === 5) return h < 22;          // Friday — closes at 22:00 UTC (NY)
  return true;                            // Mon–Thu — open
}

function isOpen(openUtc: [number, number] | null, d: Date): boolean {
  if (!openUtc) return false;
  if (!fxWeekOpen(d)) return false;      // FX market shut → no session is open
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  const [lo, hi] = openUtc;
  // Wrap window (e.g. Sydney 21→6 UTC crosses midnight): open if before hi OR at/after lo.
  return lo > hi ? h >= lo || h < hi : h >= lo && h < hi;
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
