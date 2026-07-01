import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Trade } from "../lib/api";
import { Pane } from "../components/Pane";
import { Pill } from "../components/Pill";
import { DataGrid } from "../components/DataGrid";
import { KPI } from "../components/KPI";
import {
  barsToDuration,
  colorForR,
  fmtMoney,
  fmtPriceFor,
  fmtR,
  fmtRiskFor,
  fmtTs,
  tradePnlReal,
} from "../lib/format";

type SortKey = "entry_timestamp" | "net_r" | "bars_held" | "risk_units";

export function TradesPage({ runId }: { runId: string | null }) {
  const [rows, setRows] = useState<Trade[]>([]);
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "entry_timestamp",
    dir: "desc",
  });
  const [symbol, setSymbol] = useState<string | null>(null);
  const [tf, setTf] = useState<string>("M5");
  const nav = useNavigate();

  useEffect(() => {
    if (!runId) return;
    api.runDetail(runId).then((d: any) => {
      setSymbol(d?.run?.symbol ?? null);
      setTf(d?.run?.timeframe ?? "M5");
    }).catch(() => {});
    api
      .runTrades(runId, filter === "all" ? undefined : filter, 1, 50000)
      .then(({ items }) => setRows(items));
  }, [runId, filter]);

  const sorted = useMemo(() => {
    const r = [...rows];
    r.sort((a, b) => {
      const av = (a as any)[sort.key];
      const bv = (b as any)[sort.key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (sort.key === "entry_timestamp") {
        const d = new Date(av).getTime() - new Date(bv).getTime();
        return sort.dir === "asc" ? d : -d;
      }
      const d = av - bv;
      return sort.dir === "asc" ? d : -d;
    });
    return r;
  }, [rows, sort]);

  const stats = useMemo(() => {
    const closed = sorted.filter((t) => t.net_r != null);
    const wins = closed.filter((t) => (t.net_r ?? 0) > 0);
    const losses = closed.filter((t) => (t.net_r ?? 0) < 0);
    const netSum = closed.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const winSum = wins.reduce((s, t) => s + (t.net_r ?? 0), 0);
    const lossSum = Math.abs(losses.reduce((s, t) => s + (t.net_r ?? 0), 0));
    const wr = closed.length ? (wins.length / closed.length) * 100 : 0;
    const pf = lossSum > 0 ? winSum / lossSum : winSum > 0 ? Infinity : 0;
    const avg = closed.length ? netSum / closed.length : 0;
    return { n: closed.length, wins: wins.length, losses: losses.length, netSum, wr, pf, avg };
  }, [sorted]);

  const setSortKey = (k: SortKey) =>
    setSort((s) =>
      s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "desc" }
    );

  return (
    <div className="h-full flex flex-col gap-3 p-3 min-h-0">
      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 shrink-0">
        <KPI
          label="Net R"
          value={
            <span className={colorForR(stats.netSum)}>{fmtR(stats.netSum)}</span>
          }
          sub={`${stats.n} closed trades`}
          deltaTone={stats.netSum >= 0 ? "bull" : "bear"}
        />
        <KPI label="Wins" value={stats.wins} sub={`${stats.losses} losses`} />
        <KPI label="Win Rate" value={`${stats.wr.toFixed(1)}%`} />
        <KPI
          label="Profit Factor"
          value={Number.isFinite(stats.pf) ? stats.pf.toFixed(2) : "∞"}
        />
        <KPI
          label="Avg R / Trade"
          value={
            <span className={colorForR(stats.avg)}>{fmtR(stats.avg, 3)}</span>
          }
          deltaTone={stats.avg >= 0 ? "bull" : "bear"}
        />
      </div>

      <Pane
        title="Trades"
        subtitle={`${sorted.length} loaded`}
        toolbar={
          <div className="flex items-center gap-2">
            {(["all", "open", "closed"] as const).map((f) => (
              <button
                key={f}
                className={`
                  px-2.5 py-1 rounded-ds-sm text-ds-xs uppercase tracking-wide font-medium
                  transition-colors duration-ds
                  ${
                    filter === f
                      ? "bg-bull/10 text-bull border border-bull/40"
                      : "bg-bg-elevated text-ink-muted border border-line-subtle hover:text-ink-secondary"
                  }
                `}
                onClick={() => setFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
        }
        className="flex-1 min-h-0"
      >
        <DataGrid<Trade>
          rows={sorted}
          rowKey={(t) => t.trade_id}
          onRowClick={(t) => nav(`/journal?trade=${t.trade_id}`)}
          columns={[
            {
              header: "Status",
              cell: (t) =>
                t.exit_timestamp == null ? (
                  <Pill tone="info">OPEN</Pill>
                ) : (
                  <Pill
                    tone={
                      t.exit_reason === "TP" || (t.net_r ?? 0) >= 0
                        ? "bull"
                        : t.exit_reason === "SL"
                        ? "bear"
                        : "warn"
                    }
                  >
                    {t.exit_reason ?? "CLOSED"}
                  </Pill>
                ),
            },
            {
              header: "Side",
              cell: (t) => (
                <Pill tone={t.side > 0 ? "bull" : "bear"}>
                  {t.direction.toUpperCase()}
                </Pill>
              ),
            },
            {
              header: "Leg",
              cell: (t) => (
                <span className="font-mono text-ds-sm text-ink-secondary">
                  {t.leg ?? "—"}
                </span>
              ),
            },
            {
              header: sortHeader("Entry", "entry_timestamp", sort, setSortKey),
              cell: (t) => (
                <span className="font-mono text-ds-xs text-ink-secondary">
                  {fmtTs(t.entry_timestamp)}
                </span>
              ),
            },
            {
              header: "Entry",
              cell: (t) => (
                <span className="font-mono">{fmtPriceFor(symbol, t.entry_price)}</span>
              ),
              align: "right",
            },
            {
              header: "Exit",
              cell: (t) => (
                <span className="font-mono text-ink-secondary">
                  {fmtPriceFor(symbol, t.exit_price)}
                </span>
              ),
              align: "right",
            },
            {
              header: "SL",
              cell: (t) => (
                <span className="font-mono text-ds-xs text-bear/80">
                  {fmtPriceFor(symbol, t.stop_price)}
                </span>
              ),
              align: "right",
            },
            {
              header: "TP",
              cell: (t) => (
                <span className="font-mono text-ds-xs text-bull/80">
                  {fmtPriceFor(symbol, t.take_profit_price)}
                </span>
              ),
              align: "right",
            },
            {
              header: sortHeader("Risk", "risk_units", sort, setSortKey),
              cell: (t) => (
                <span className="font-mono text-ds-xs text-ink-secondary">
                  {fmtRiskFor(symbol, t.risk_units)}
                </span>
              ),
              align: "right",
            },
            {
              header: sortHeader("Held", "bars_held", sort, setSortKey),
              cell: (t) => (
                <span className="font-mono text-ink-secondary">
                  {barsToDuration(t.bars_held, tf)}
                </span>
              ),
              align: "right",
            },
            {
              header: sortHeader("Net R", "net_r", sort, setSortKey),
              cell: (t) => (
                <span className={`font-mono ${colorForR(t.net_r)}`}>
                  {fmtR(t.net_r)}
                </span>
              ),
              align: "right",
            },
            {
              header: "$ PnL",
              cell: (t) => {
                const pnl = tradePnlReal(symbol, t.net_r, t.risk_units, t.raw_features);
                return (
                  <span className={`font-mono font-semibold ${colorForR(pnl)}`}>
                    {fmtMoney(pnl, 0)}
                  </span>
                );
              },
              align: "right",
            },
          ]}
        />
      </Pane>
    </div>
  );
}

function sortHeader(
  label: string,
  key: SortKey,
  sort: { key: SortKey; dir: "asc" | "desc" },
  setSortKey: (k: SortKey) => void
) {
  const active = sort.key === key;
  return (
    <button
      onClick={() => setSortKey(key)}
      className={`inline-flex items-center gap-1 transition-colors ${
        active ? "text-ink-primary" : "text-ink-muted hover:text-ink-secondary"
      }`}
    >
      {label}
      {active && (
        <span className="text-bull">
          {sort.dir === "asc" ? "↑" : "↓"}
        </span>
      )}
    </button>
  );
}
