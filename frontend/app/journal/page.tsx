"use client";
import { useEffect, useMemo, useState } from "react";
import { useInstrument } from "@/lib/instrument";
import { client, type ServiceKey } from "@/lib/client";
import {
  PageHeader,
  Card,
  Tabs,
  Button,
  Badge,
  EmptyState,
  Skeleton,
} from "@/components/ui";

interface JournalEvent {
  id: number;
  timestamp: string;
  trade_ref: string;
  strategy: string;
  event_type: string;
  price: number;
  context: Record<string, unknown>;
}

interface BacktestTrade {
  date: string;
  year: number;
  strategy: string;
  direction: string;
  entry: number;
  sl: number;
  tp: number;
  exit_price: number;
  pnl_sized: number;
  status: string;
  hold_human: string;
  r_mult: number;
}

const STRATEGY_META: Record<string, { label: string; color: string }> = {
  alpha_sweep: { label: "Alpha", color: "var(--color-info)" },
  micro_alpha_sweep: { label: "Alpha", color: "var(--color-info)" },
  micro_alpha_sweep_oil: { label: "Alpha", color: "var(--color-info)" },
  mean_rev: { label: "MRev", color: "var(--color-win)" },
  cross_market: { label: "Cross", color: "var(--color-warn)" },
};

function strategyTag(strategy: string) {
  const key = Object.keys(STRATEGY_META).find((k) => strategy?.includes(k));
  if (!key) {
    return <span className="text-[10px] uppercase tracking-[0.6px] text-[var(--color-text-muted)]">SYS</span>;
  }
  const meta = STRATEGY_META[key];
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-medium" style={{ color: meta.color }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} aria-hidden />
      {meta.label}
    </span>
  );
}

function eventTone(type: string): "win" | "loss" | "warn" | "info" | "neutral" {
  if (!type) return "neutral";
  if (type.includes("ENTRY") || type === "SIGNAL") return "win";
  if (type.includes("EXIT") || type.includes("SL") || type.includes("TP_FILLED")) return "loss";
  if (type.includes("BREAK_EVEN") || type.includes("BE")) return "info";
  if (type.includes("SKIP") || type.includes("PAUSE") || type.includes("WARN")) return "warn";
  if (type.includes("ERROR") || type.includes("FAILED")) return "loss";
  return "neutral";
}

function formatTime(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/** Compact relative-time string ('4m', '2h', '3d'). */
function relativeAge(iso?: string, now: number = Date.now()): string {
  if (!iso) return "";
  const ageMs = now - new Date(iso).getTime();
  if (ageMs < 0) return "now";
  const sec = Math.floor(ageMs / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.floor(hr / 24);
  return `${day}d`;
}

function formatBacktestDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function JournalPage() {
  const { instrument } = useInstrument();
  const svc = instrument as ServiceKey;
  const [tab, setTab] = useState<"live" | "backtest">("live");
  const [filter, setFilter] = useState({ strategy: "", event_type: "" });
  const [events, setEvents] = useState<JournalEvent[]>([]);
  const [btTrades, setBtTrades] = useState<BacktestTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      try {
        if (tab === "live") {
          const params: Record<string, unknown> = { limit: 100 };
          if (filter.strategy) params.strategy = filter.strategy;
          if (filter.event_type) params.event_type = filter.event_type;
          const data = await client(svc).journal<{ events?: JournalEvent[] }>(params);
          if (!cancelled) setEvents(data?.events ?? []);
        } else {
          const params: Record<string, unknown> = { source: "backtest", limit: 500 };
          if (filter.strategy) params.strategy = filter.strategy;
          const data = await client(svc).trades<{ trades?: BacktestTrade[] }>({ ...params });
          if (!cancelled) setBtTrades(data?.trades ?? []);
        }
      } catch {
        if (!cancelled) {
          setEvents([]);
          setBtTrades([]);
        }
      }
      if (!cancelled) setLoading(false);
    };
    run();
    return () => { cancelled = true; };
  }, [svc, tab, filter, refreshKey]);

  const liveCounts = useMemo(() => {
    const total = events.length;
    const errors = events.filter((e) => e.event_type?.includes("ERROR") || e.event_type?.includes("FAILED")).length;
    const entries = events.filter((e) => e.event_type?.includes("ENTRY")).length;
    const exits = events.filter((e) => e.event_type?.includes("EXIT") || e.event_type?.includes("FILLED")).length;
    return { total, errors, entries, exits };
  }, [events]);

  // Detect quiet-period: newest event > 2 hours old. Tells the user that
  // what they're looking at is stale (e.g. weekend / market closed) rather
  // than current activity.
  const newestAgeMs = useMemo(() => {
    if (events.length === 0) return null;
    const newest = events.reduce((acc, e) => {
      const t = new Date(e.timestamp).getTime();
      return t > acc ? t : acc;
    }, 0);
    return Date.now() - newest;
  }, [events]);
  const isStale = newestAgeMs !== null && newestAgeMs > 2 * 60 * 60 * 1000;
  const staleLabel = newestAgeMs !== null
    ? relativeAge(new Date(Date.now() - newestAgeMs).toISOString())
    : "";

  return (
    <div className="p-3 sm:p-6 max-w-[1280px] mx-auto">
      <PageHeader
        title="Journal"
        description="Event log and trade narratives"
        actions={
          <Tabs.Root value={tab} onValueChange={(v) => setTab(v as "live" | "backtest")}>
            <Tabs.List>
              <Tabs.Trigger value="live">Live events</Tabs.Trigger>
              <Tabs.Trigger value="backtest">Backtest journal</Tabs.Trigger>
            </Tabs.List>
          </Tabs.Root>
        }
      />

      {/* Staleness banner — newest event > 2h old means quiet period */}
      {tab === "live" && isStale ? (
        <Card padded surface={2} className="mb-4 border-[var(--color-warn)]/30">
          <div className="flex items-center gap-3 text-[12px]">
            <span className="text-[16px]" aria-hidden>🌙</span>
            <div className="flex-1">
              <div className="text-[var(--color-warn)] font-medium">Quiet period — newest event is {staleLabel} old</div>
              <div className="text-[12.5px] text-[var(--color-text-dim)] leading-relaxed">
                Markets may be closed, or no scans have triggered events recently. The list below shows historical activity, not live state.
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      {/* Live event counts */}
      {tab === "live" && events.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4 hom-stagger-children">
          <Card padded lift className="hom-stagger">
            <div className="flex flex-col gap-1">
              <span className="text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)]">Events</span>
              <span className="num text-[20px] font-semibold text-[var(--color-text)]">{liveCounts.total}</span>
            </div>
          </Card>
          <Card padded lift className="hom-stagger">
            <div className="flex flex-col gap-1">
              <span className="text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)]">Entries</span>
              <span className="num text-[20px] font-semibold text-[var(--color-win)]">{liveCounts.entries}</span>
            </div>
          </Card>
          <Card padded lift className="hom-stagger">
            <div className="flex flex-col gap-1">
              <span className="text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)]">Exits</span>
              <span className="num text-[20px] font-semibold text-[var(--color-loss)]">{liveCounts.exits}</span>
            </div>
          </Card>
          <Card padded lift className="hom-stagger">
            <div className="flex flex-col gap-1">
              <span className="text-[11.5px] font-medium uppercase tracking-[1.4px] text-[var(--color-text-dim)]">Errors</span>
              <span className={`num text-[20px] font-semibold ${liveCounts.errors > 0 ? "text-[var(--color-loss)]" : "text-[var(--color-text-muted)]"}`}>{liveCounts.errors}</span>
            </div>
          </Card>
        </div>
      ) : null}

      {/* Filter bar */}
      <Card padded surface={1} className="mb-4">
        <div className="flex gap-2 flex-wrap items-center">
          <select
            value={filter.strategy}
            onChange={(e) => setFilter({ ...filter, strategy: e.target.value })}
            aria-label="Filter by strategy"
          >
            <option value="">All Strategies</option>
            <option value="alpha_sweep">Alpha-Sweep</option>
            <option value="mean_rev">Mean-Rev</option>
            <option value="cross_market">Cross-Market</option>
            {tab === "live" ? <option value="system">System</option> : null}
          </select>
          {tab === "live" ? (
            <select
              value={filter.event_type}
              onChange={(e) => setFilter({ ...filter, event_type: e.target.value })}
              aria-label="Filter by event type"
            >
              <option value="">All Events</option>
              <option value="ENTRY_FILLED">Entry</option>
              <option value="EXIT_FILLED">Exit</option>
              <option value="SIGNAL_SKIPPED">Skipped</option>
              <option value="BREAK_EVEN">Break-Even</option>
              <option value="ERROR">Errors</option>
              <option value="DAILY_SCAN_START">Daily Scan</option>
            </select>
          ) : null}
          <Button size="sm" variant="secondary" onClick={() => setRefreshKey((k) => k + 1)}>
            Refresh
          </Button>
          {(filter.strategy || filter.event_type) ? (
            <Button size="sm" variant="ghost" onClick={() => setFilter({ strategy: "", event_type: "" })}>
              Reset
            </Button>
          ) : null}
        </div>
      </Card>

      {/* Event / trade list */}
      <Card>
        <Card.Header>
          <Card.Title>{tab === "live" ? "Live Events" : "Backtest Journal"}</Card.Title>
          <span className="text-[12.5px] text-[var(--color-text-dim)]">
            {tab === "live"
              ? `${events.length.toLocaleString()} of last 100`
              : `${btTrades.length.toLocaleString()} of last 500`}
          </span>
        </Card.Header>
        <div className="max-h-[700px] overflow-auto">
          {loading ? (
            <div className="p-3 flex flex-col gap-1.5">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} height={28} />
              ))}
            </div>
          ) : tab === "live" && events.length === 0 ? (
            <EmptyState
              title="No events yet"
              description="System will log at next scheduled scan (22:00 UTC or 08:00–10:30 UTC)."
            />
          ) : tab === "backtest" && btTrades.length === 0 ? (
            <EmptyState
              title="No backtest results in DB"
              description="Run a backtest first from the Backtest page."
            />
          ) : tab === "live" ? (
            <ul className="divide-y divide-[var(--color-border)]/60">
              {events.map((e) => {
                const tone = eventTone(e.event_type);
                const ctx =
                  e.context && Object.keys(e.context).length > 0
                    ? Object.entries(e.context)
                        .map(([k, v]) => `${k}=${typeof v === "number" ? (v as number).toFixed(2) : v}`)
                        .join(" · ")
                    : "";
                const age = relativeAge(e.timestamp);
                const isAged = (Date.now() - new Date(e.timestamp).getTime()) > 2 * 60 * 60 * 1000;
                return (
                  <li
                    key={e.id}
                    className="px-3 py-2 flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3 hover:bg-[var(--color-surface-2)]/60 transition-colors"
                  >
                    <span className="flex items-baseline gap-2 sm:min-w-[200px] shrink-0">
                      <span className="num text-[12.5px] text-[var(--color-text-dim)]">
                        {formatTime(e.timestamp)}
                      </span>
                      {age ? (
                        <span className={`num text-[10px] ${isAged ? "text-[var(--color-text-muted)] opacity-60" : "text-[var(--color-text-dim)]"}`}>
                          {age}
                        </span>
                      ) : null}
                    </span>
                    <span className="sm:min-w-[60px] shrink-0">{strategyTag(e.strategy)}</span>
                    <Badge tone={tone} variant="soft" className="shrink-0">
                      {e.event_type}
                    </Badge>
                    {e.price ? (
                      <span className="num text-[11px] text-[var(--color-text)] sm:min-w-[70px] shrink-0">
                        ${e.price.toFixed(2)}
                      </span>
                    ) : null}
                    <span className="text-[11px] text-[var(--color-text-dim)] truncate flex-1">
                      {e.trade_ref && e.trade_ref !== "SYSTEM" ? (
                        <span className="num text-[var(--color-info)] mr-2">[{e.trade_ref}]</span>
                      ) : null}
                      {ctx ? <span className="num text-[var(--color-text-muted)]">{ctx}</span> : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <ul className="divide-y divide-[var(--color-border)]/60">
              {btTrades.map((t, i) => (
                <li
                  key={`${t.date}-${t.entry}-${i}`}
                  className="px-3 py-2 flex items-center gap-3 hover:bg-[var(--color-surface-2)]/60 transition-colors"
                >
                  <span className="num text-[12.5px] text-[var(--color-text-dim)] min-w-[110px] shrink-0">
                    {formatBacktestDate(t.date)}
                  </span>
                  <span className="min-w-[60px] shrink-0">{strategyTag(t.strategy)}</span>
                  <Badge tone={t.direction === "LONG" ? "win" : "loss"} variant="soft" className="shrink-0">
                    {t.direction}
                  </Badge>
                  <span className="num text-[11px] text-[var(--color-text)] min-w-[60px] shrink-0">
                    ${t.entry.toFixed(0)}
                  </span>
                  <span className="text-[var(--color-text-muted)] hidden sm:inline">→</span>
                  <span className="num text-[11px] text-[var(--color-text-dim)] min-w-[60px] shrink-0">
                    ${t.exit_price.toFixed(0)}
                  </span>
                  <span
                    className={`num text-[12px] font-semibold min-w-[80px] shrink-0 ${
                      t.pnl_sized >= 0 ? "text-[var(--color-win)]" : "text-[var(--color-loss)]"
                    }`}
                  >
                    {t.pnl_sized >= 0 ? "+" : ""}${t.pnl_sized.toFixed(0)}
                  </span>
                  <span
                    className={`num text-[11px] min-w-[50px] shrink-0 ${
                      t.r_mult > 0
                        ? "text-[var(--color-win)]"
                        : t.r_mult < 0
                          ? "text-[var(--color-loss)]"
                          : "text-[var(--color-text-muted)]"
                    }`}
                  >
                    {t.r_mult > 0 ? "+" : ""}{t.r_mult.toFixed(1)}R
                  </span>
                  <span className="text-[11px] uppercase text-[var(--color-warn)] min-w-[80px] shrink-0">
                    {t.status}
                  </span>
                  <span className="text-[12.5px] text-[var(--color-text-dim)] truncate hidden md:inline">
                    {t.hold_human}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
