import { useMemo, useState } from "react";
import { Search, Download, Filter as FilterIcon, RotateCcw, X } from "lucide-react";
import { Trade } from "../lib/api";
import {
  FilterState,
  EMPTY_FILTER,
  hasAnyFilter,
  holdBucketOf,
  outcomeOf,
  overnightOf,
  rBucketOf,
  sessionOf,
  statusOf,
  toCsv,
  downloadCsv,
} from "../lib/filters";
import { ChipGroup, Chip } from "./FilterChips";

type Counts = Record<string, number>;

function bumpCount(map: Counts, k?: string | null) {
  if (!k) return;
  map[k] = (map[k] ?? 0) + 1;
}

export function FilterBar({
  trades,
  filtered,
  filter,
  setFilter,
  symbol,
  tf = "M5",
}: {
  trades: Trade[];
  filtered: Trade[];
  filter: FilterState;
  setFilter: (f: FilterState) => void;
  symbol?: string | null;
  tf?: string;
}) {
  // Collapsed by default — keeps Trades table prominent. Click "Filters" to expand.
  const [expanded, setExpanded] = useState(false);

  // Counts across the UNFILTERED set so chips always show how many would qualify.
  // Skill: data-density — show counts inline so chips read like facets.
  const counts = useMemo(() => {
    const c = {
      status: {} as Counts,
      side: {} as Counts,
      leg: {} as Counts,
      regime: {} as Counts,
      outcome: {} as Counts,
      rBucket: {} as Counts,
      session: {} as Counts,
      year: {} as Counts,
      holdBucket: {} as Counts,
      overnight: {} as Counts,
    };
    trades.forEach((t) => {
      bumpCount(c.status, statusOf(t));
      bumpCount(c.side, t.side > 0 ? "LONG" : "SHORT");
      bumpCount(c.leg, t.leg);
      bumpCount(c.regime, t.regime);
      bumpCount(c.outcome, outcomeOf(t.net_r));
      bumpCount(c.rBucket, rBucketOf(t.net_r));
      bumpCount(c.session, sessionOf(t));
      bumpCount(c.year, (t.entry_timestamp ?? "").slice(0, 4));
      bumpCount(c.holdBucket, holdBucketOf(t.bars_held, tf));
      bumpCount(c.overnight, overnightOf(t));
    });
    return c;
  }, [trades, tf]);

  const toggle = <K extends keyof FilterState>(
    key: K,
    val: string
  ) => {
    const cur = filter[key];
    if (cur instanceof Set) {
      const next = new Set(cur as Set<string>);
      if (next.has(val)) next.delete(val);
      else next.add(val);
      setFilter({ ...filter, [key]: next });
    }
  };

  const clearKey = <K extends keyof FilterState>(key: K) => {
    setFilter({ ...filter, [key]: new Set() } as FilterState);
  };

  const active = hasAnyFilter(filter);

  const applyPreset = (name: string) => {
    if (name === "winners") {
      setFilter({ ...EMPTY_FILTER, outcome: new Set(["WIN"]) });
    } else if (name === "losers") {
      setFilter({ ...EMPTY_FILTER, outcome: new Set(["LOSS"]) });
    } else if (name === "tp") {
      setFilter({ ...EMPTY_FILTER, status: new Set(["TP"]) });
    } else if (name === "sl") {
      setFilter({ ...EMPTY_FILTER, status: new Set(["SL"]) });
    } else if (name === "outliers") {
      setFilter({ ...EMPTY_FILTER, rBucket: new Set(["+4R+"]) });
    } else if (name === "open") {
      setFilter({ ...EMPTY_FILTER, status: new Set(["OPEN"]) });
    } else if (name === "ny") {
      setFilter({ ...EMPTY_FILTER, session: new Set(["ny"]) });
    } else if (name === "london") {
      setFilter({ ...EMPTY_FILTER, session: new Set(["london"]) });
    } else if (name === "thisyear") {
      const y = String(new Date().getUTCFullYear());
      setFilter({ ...EMPTY_FILTER, year: new Set([y]) });
    } else if (name === "overnight") {
      setFilter({ ...EMPTY_FILTER, overnight: new Set(["overnight"]) });
    }
  };

  const onExport = () => {
    const csv = toCsv(filtered, symbol);
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    downloadCsv(`trades-${stamp}.csv`, csv);
  };

  // Sort years desc, leg/regime alpha
  const orderedKeys = (m: Counts, desc = true) =>
    Object.keys(m).sort((a, b) => (desc ? b.localeCompare(a) : a.localeCompare(b)));

  const STATUS_ORDER = ["TP", "SL_BE", "SL", "TIMEOUT", "OPEN"];
  const HOLD_ORDER: import("../lib/filters").HoldBucket[] = ["<1h", "1-4h", "4-24h", "1d+"];
  const R_ORDER: import("../lib/filters").RBucket[] = ["<-1R", "-1..0", "0..+1", "+1..+2", "+2..+4", "+4R+"];
  const SESSION_ORDER: import("../lib/filters").Session[] = ["asia", "london", "ny", "off"];

  return (
    <div className="flex flex-col gap-2">
      {/* Top row: search + preset + export + filter toggle + counter */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search
            size={13}
            className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-muted pointer-events-none"
          />
          <input
            value={filter.search}
            onChange={(e) => setFilter({ ...filter, search: e.target.value })}
            placeholder="search trade_ref, leg, regime…"
            className="
              bg-bg-input border border-line-base rounded-ds-sm
              text-ds-sm text-ink-primary placeholder:text-ink-muted
              pl-7 pr-2 py-1 w-full sm:w-72
              focus:outline-none focus:border-brass
            "
          />
        </div>

        <div className="flex items-center gap-1">
          <span className="text-ds-xs uppercase tracking-wide text-ink-muted">
            preset
          </span>
          <PresetBtn onClick={() => applyPreset("winners")}>Winners</PresetBtn>
          <PresetBtn onClick={() => applyPreset("losers")}>Losers</PresetBtn>
          <PresetBtn onClick={() => applyPreset("tp")}>TP only</PresetBtn>
          <PresetBtn onClick={() => applyPreset("sl")}>SL only</PresetBtn>
          <PresetBtn onClick={() => applyPreset("outliers")}>4R+ outliers</PresetBtn>
          <PresetBtn onClick={() => applyPreset("overnight")}>Overnight</PresetBtn>
          <PresetBtn onClick={() => applyPreset("ny")}>NY session</PresetBtn>
          <PresetBtn onClick={() => applyPreset("london")}>London</PresetBtn>
          <PresetBtn onClick={() => applyPreset("thisyear")}>This year</PresetBtn>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-ds-xs text-ink-muted font-mono">
            {filtered.length.toLocaleString()} / {trades.length.toLocaleString()}
          </span>
          <button
            onClick={onExport}
            className="
              inline-flex items-center gap-1.5 px-2 py-1
              text-ds-xs text-ink-secondary
              border border-line-base rounded-ds-sm
              hover:text-ink-primary hover:border-line-strong
              transition-colors duration-ds
            "
            title="Export filtered CSV"
          >
            <Download size={12} />
            CSV
          </button>
          <button
            onClick={() => setExpanded((x) => !x)}
            className={`
              relative inline-flex items-center gap-1.5 px-2 py-1
              text-ds-xs border rounded-ds-sm
              transition-colors duration-ds
              ${
                expanded || active
                  ? "text-brass-hi border-brass/40 bg-brass/10"
                  : "text-ink-secondary border-line-base hover:text-ink-primary hover:border-line-strong"
              }
            `}
          >
            <FilterIcon size={12} />
            {expanded ? "Hide filters" : "Filters"}
            {active && (
              <span className="text-[10px] font-mono px-1 py-px rounded-full bg-brass text-bg-base font-bold">
                {countActive(filter)}
              </span>
            )}
          </button>
          {active && (
            <button
              onClick={() => setFilter(EMPTY_FILTER)}
              className="inline-flex items-center gap-1.5 px-2 py-1 text-ds-xs text-bear/80 hover:text-bear border border-bear/30 rounded-ds-sm"
              title="Clear all filters"
            >
              <RotateCcw size={11} />
              Reset
            </button>
          )}
        </div>
      </div>

      {/* Chip facets */}
      {expanded && (
        <div className="flex flex-col gap-2 p-3 bg-bg-base border border-line-subtle rounded-ds">
          <ChipGroup
            label="Outcome"
            onClear={() => clearKey("outcome")}
            active={filter.outcome.size > 0}
          >
            <Chip
              active={filter.outcome.has("WIN")}
              tone="bull"
              onClick={() => toggle("outcome", "WIN")}
              count={counts.outcome["WIN"]}
            >
              Winners
            </Chip>
            <Chip
              active={filter.outcome.has("LOSS")}
              tone="bear"
              onClick={() => toggle("outcome", "LOSS")}
              count={counts.outcome["LOSS"]}
            >
              Losers
            </Chip>
            <Chip
              active={filter.outcome.has("BE")}
              tone="warn"
              onClick={() => toggle("outcome", "BE")}
              count={counts.outcome["BE"]}
            >
              Breakeven
            </Chip>
          </ChipGroup>

          <ChipGroup
            label="Status"
            onClear={() => clearKey("status")}
            active={filter.status.size > 0}
          >
            {STATUS_ORDER.filter((s) => counts.status[s]).map((s) => (
              <Chip
                key={s}
                active={filter.status.has(s)}
                tone={s === "TP" ? "bull" : s === "SL" ? "bear" : s === "TIMEOUT" ? "warn" : s === "OPEN" ? "info" : "neutral"}
                onClick={() => toggle("status", s)}
                count={counts.status[s]}
              >
                {s}
              </Chip>
            ))}
          </ChipGroup>

          <ChipGroup
            label="Side"
            onClear={() => clearKey("side")}
            active={filter.side.size > 0}
          >
            <Chip
              active={filter.side.has("LONG")}
              tone="bull"
              onClick={() => toggle("side", "LONG")}
              count={counts.side["LONG"]}
            >
              LONG
            </Chip>
            <Chip
              active={filter.side.has("SHORT")}
              tone="bear"
              onClick={() => toggle("side", "SHORT")}
              count={counts.side["SHORT"]}
            >
              SHORT
            </Chip>
          </ChipGroup>

          {Object.keys(counts.leg).length > 0 && (
            <ChipGroup
              label="Leg"
              onClear={() => clearKey("leg")}
              active={filter.leg.size > 0}
            >
              {orderedKeys(counts.leg, false).map((leg) => (
                <Chip
                  key={leg}
                  active={filter.leg.has(leg)}
                  onClick={() => toggle("leg", leg)}
                  count={counts.leg[leg]}
                >
                  {leg}
                </Chip>
              ))}
            </ChipGroup>
          )}

          {Object.keys(counts.regime).length > 0 && (
            <ChipGroup
              label="Regime"
              onClear={() => clearKey("regime")}
              active={filter.regime.size > 0}
            >
              {orderedKeys(counts.regime, false).map((rg) => (
                <Chip
                  key={rg}
                  active={filter.regime.has(rg)}
                  onClick={() => toggle("regime", rg)}
                  count={counts.regime[rg]}
                >
                  {rg}
                </Chip>
              ))}
            </ChipGroup>
          )}

          <ChipGroup
            label="R bucket"
            onClear={() => clearKey("rBucket")}
            active={filter.rBucket.size > 0}
          >
            {R_ORDER.filter((b) => counts.rBucket[b]).map((b) => (
              <Chip
                key={b}
                active={filter.rBucket.has(b)}
                tone={b.startsWith("<") || b.startsWith("-") ? "bear" : "bull"}
                onClick={() => toggle("rBucket", b)}
                count={counts.rBucket[b]}
              >
                {b}
              </Chip>
            ))}
          </ChipGroup>

          <ChipGroup
            label="Hold"
            onClear={() => clearKey("holdBucket")}
            active={filter.holdBucket.size > 0}
          >
            {HOLD_ORDER.filter((h) => counts.holdBucket[h]).map((h) => (
              <Chip
                key={h}
                active={filter.holdBucket.has(h)}
                onClick={() => toggle("holdBucket", h)}
                count={counts.holdBucket[h]}
              >
                {h}
              </Chip>
            ))}
          </ChipGroup>

          <ChipGroup
            label="Carry"
            onClear={() => clearKey("overnight")}
            active={filter.overnight.size > 0}
          >
            <Chip
              active={filter.overnight.has("overnight")}
              tone="bull"
              onClick={() => toggle("overnight", "overnight")}
              count={counts.overnight["overnight"]}
            >
              Overnight
            </Chip>
            <Chip
              active={filter.overnight.has("intraday")}
              tone="bear"
              onClick={() => toggle("overnight", "intraday")}
              count={counts.overnight["intraday"]}
            >
              Same-day
            </Chip>
          </ChipGroup>

          <ChipGroup
            label="Session"
            onClear={() => clearKey("session")}
            active={filter.session.size > 0}
          >
            {SESSION_ORDER.filter((s) => counts.session[s]).map((s) => (
              <Chip
                key={s}
                active={filter.session.has(s)}
                onClick={() => toggle("session", s)}
                count={counts.session[s]}
              >
                {s}
              </Chip>
            ))}
          </ChipGroup>

          {Object.keys(counts.year).length > 0 && (
            <ChipGroup
              label="Year"
              onClear={() => clearKey("year")}
              active={filter.year.size > 0}
            >
              {orderedKeys(counts.year, true).map((y) => (
                <Chip
                  key={y}
                  active={filter.year.has(y)}
                  onClick={() => toggle("year", y)}
                  count={counts.year[y]}
                >
                  {y}
                </Chip>
              ))}
            </ChipGroup>
          )}

          {/* Range filters — date, R, $ PnL */}
          <div className="flex flex-wrap items-center gap-4 pt-2 border-t border-line-subtle">
            <RangeFilter
              label="Date"
              kind="date"
              from={filter.dateFrom ?? ""}
              to={filter.dateTo ?? ""}
              onFrom={(v) => setFilter({ ...filter, dateFrom: v || null })}
              onTo={(v) => setFilter({ ...filter, dateTo: v || null })}
              onClear={
                filter.dateFrom || filter.dateTo
                  ? () => setFilter({ ...filter, dateFrom: null, dateTo: null })
                  : undefined
              }
            />
            <RangeFilter
              label="Net R"
              kind="number"
              from={filter.rMin?.toString() ?? ""}
              to={filter.rMax?.toString() ?? ""}
              onFrom={(v) => setFilter({ ...filter, rMin: v === "" ? null : Number(v) })}
              onTo={(v) => setFilter({ ...filter, rMax: v === "" ? null : Number(v) })}
              onClear={
                filter.rMin != null || filter.rMax != null
                  ? () => setFilter({ ...filter, rMin: null, rMax: null })
                  : undefined
              }
              placeholder={["min R", "max R"]}
            />
            <RangeFilter
              label="$ PnL"
              kind="number"
              from={filter.pnlMin?.toString() ?? ""}
              to={filter.pnlMax?.toString() ?? ""}
              onFrom={(v) => setFilter({ ...filter, pnlMin: v === "" ? null : Number(v) })}
              onTo={(v) => setFilter({ ...filter, pnlMax: v === "" ? null : Number(v) })}
              onClear={
                filter.pnlMin != null || filter.pnlMax != null
                  ? () => setFilter({ ...filter, pnlMin: null, pnlMax: null })
                  : undefined
              }
              placeholder={["min $", "max $"]}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function RangeFilter({
  label,
  kind,
  from,
  to,
  onFrom,
  onTo,
  onClear,
  placeholder = ["from", "to"],
}: {
  label: string;
  kind: "date" | "number";
  from: string;
  to: string;
  onFrom: (v: string) => void;
  onTo: (v: string) => void;
  onClear?: () => void;
  placeholder?: [string, string];
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-ds-xs uppercase tracking-wide text-ink-muted shrink-0">
        {label}
      </span>
      <input
        type={kind}
        value={from}
        onChange={(e) => onFrom(e.target.value)}
        placeholder={placeholder[0]}
        className="
          bg-bg-input border border-line-base rounded-ds-sm
          text-ds-sm font-mono text-ink-primary placeholder:text-ink-muted
          px-2 py-0.5 w-28
          focus:outline-none focus:border-brass
        "
      />
      <span className="text-ink-muted">→</span>
      <input
        type={kind}
        value={to}
        onChange={(e) => onTo(e.target.value)}
        placeholder={placeholder[1]}
        className="
          bg-bg-input border border-line-base rounded-ds-sm
          text-ds-sm font-mono text-ink-primary placeholder:text-ink-muted
          px-2 py-0.5 w-28
          focus:outline-none focus:border-brass
        "
      />
      {onClear && (
        <button
          onClick={onClear}
          className="text-ink-muted hover:text-ink-primary p-0.5"
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}

function PresetBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="
        px-2 py-0.5 rounded-ds-sm text-ds-xs
        bg-bg-elevated border border-line-base
        text-ink-secondary hover:text-ink-primary hover:border-line-strong
        transition-colors duration-ds
      "
    >
      {children}
    </button>
  );
}

function countActive(f: FilterState): number {
  return (
    f.status.size +
    f.side.size +
    f.leg.size +
    f.regime.size +
    f.outcome.size +
    f.rBucket.size +
    f.session.size +
    f.year.size +
    f.holdBucket.size +
    f.overnight.size +
    (f.search.trim() ? 1 : 0)
  );
}
