import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Trade } from "../lib/api";
import { Pane } from "../components/Pane";
import { DataGrid } from "../components/DataGrid";
import { colorForR, fmtPrice, fmtR, fmtTs } from "../lib/format";

type SortKey = "entry_timestamp" | "net_r" | "bars_held" | "risk_units";

export function TradesPage({ runId }: { runId: string | null }) {
  const [rows, setRows] = useState<Trade[]>([]);
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "entry_timestamp",
    dir: "desc",
  });
  const nav = useNavigate();

  useEffect(() => {
    if (!runId) return;
    api
      .runTrades(runId, filter === "all" ? undefined : filter, 1, 500)
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

  const summary = useMemo(() => {
    const closed = sorted.filter((t) => t.net_r != null);
    const wins = closed.filter((t) => (t.net_r ?? 0) > 0).length;
    const losses = closed.filter((t) => (t.net_r ?? 0) < 0).length;
    const netSum = closed.reduce((s, t) => s + (t.net_r ?? 0), 0);
    return { n: closed.length, wins, losses, netSum };
  }, [sorted]);

  const setSortKey = (k: SortKey) =>
    setSort((s) =>
      s.key === k ? { key: k, dir: s.dir === "asc" ? "desc" : "asc" } : { key: k, dir: "desc" }
    );

  return (
    <Pane
      title="Trades"
      right={
        <span>
          {summary.n} closed · {summary.wins}W / {summary.losses}L · net{" "}
          <span className={colorForR(summary.netSum)}>{fmtR(summary.netSum)}</span>
        </span>
      }
    >
      <div className="flex gap-2 px-2 py-1 border-b border-term-amberDim text-term-xs">
        {(["all", "open", "closed"] as const).map((f) => (
          <button
            key={f}
            className={`px-2 py-0.5 uppercase border ${
              filter === f
                ? "border-term-amber text-term-amber"
                : "border-term-amberDim text-term-textMuted"
            }`}
            onClick={() => setFilter(f)}
          >
            {f}
          </button>
        ))}
      </div>
      <DataGrid<Trade>
        rows={sorted}
        onRowClick={(t) => nav(`/journal?trade=${t.trade_id}`)}
        columns={[
          { header: "Status", cell: (t) => t.exit_timestamp == null ? "OPEN" : (t.exit_reason ?? "CLOSED") },
          { header: "Side", cell: (t) => (
            <span className={t.side > 0 ? "text-term-green" : "text-term-red"}>
              {t.direction.toUpperCase()}
            </span>
          )},
          { header: "Leg", cell: (t) => t.leg ?? "—" },
          {
            header: makeSortHeader("Entry TS", "entry_timestamp", sort, setSortKey),
            cell: (t) => fmtTs(t.entry_timestamp),
          },
          { header: "Entry", cell: (t) => fmtPrice(t.entry_price), align: "right" },
          { header: "Exit", cell: (t) => fmtPrice(t.exit_price), align: "right" },
          {
            header: makeSortHeader("Risk", "risk_units", sort, setSortKey),
            cell: (t) => fmtPrice(t.risk_units),
            align: "right",
          },
          {
            header: makeSortHeader("Bars", "bars_held", sort, setSortKey),
            cell: (t) => t.bars_held ?? "—",
            align: "right",
          },
          {
            header: makeSortHeader("Net R", "net_r", sort, setSortKey),
            cell: (t) => <span className={colorForR(t.net_r)}>{fmtR(t.net_r)}</span>,
            align: "right",
          },
        ]}
      />
    </Pane>
  );
}

function makeSortHeader(
  label: string,
  key: SortKey,
  sort: { key: SortKey; dir: "asc" | "desc" },
  setSortKey: (k: SortKey) => void
) {
  const active = sort.key === key;
  return (
    <button
      onClick={() => setSortKey(key)}
      className={active ? "text-term-amber" : "text-term-amberDim"}
    >
      {label}
      {active ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
    </button>
  );
}
