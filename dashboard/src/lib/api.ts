// Typed REST client for dashboard_backend.

export type Run = {
  run_id: string;
  run_ref: string;
  mode: string;
  strategy_id: string;
  symbol: string;
  timeframe: string;
  start_ts: string;
  end_ts: string | null;
  git_sha: string | null;
};

export type Trade = {
  trade_id: string;
  trade_ref: string;
  run_id: string;
  direction: string;
  side: number;
  entry_timestamp: string;
  entry_price: number;
  stop_price: number;
  take_profit_price: number | null;
  risk_units: number;
  exit_timestamp: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  bars_held: number | null;
  net_r: number | null;
  gross_r: number | null;
  cost_r: number | null;
  leg: string | null;
  regime: string | null;
  partial_taken: boolean | null;
  partial_r: number | null;
  raw_features?: Record<string, unknown> | null;
};

export type JournalEvt = {
  event_id: number;
  ts: string;
  event_type: string;
  detail: Record<string, unknown>;
};

export type SignalRow = {
  signal_id: number;
  run_id: string;
  ts: string;
  status: string;
  reason: string | null;
  zone_id: number | null;
  detail: Record<string, unknown> | null;
};

export type BarWalkRow = {
  bar_ts: string;
  phase: string;
  open: number;
  high: number;
  low: number;
  close: number;
  mfe_r: number | null;
  mae_r: number | null;
  unrealised_r: number | null;
  distance_to_entry_r: number | null;
  distance_to_stop_r: number | null;
  distance_to_tp_r: number | null;
};

export type AccountSnap = {
  snap_id: number;
  ts: string;
  balance: number | null;
  equity: number | null;
  open_pnl: number | null;
  open_position: number | null;
};

export type FunnelBucket = { status: string; count: number };

async function j<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const api = {
  health: () => j<{ status: string }>("/api/health"),
  runs: (limit = 50, mode?: "live" | "bt" | string) =>
    j<Run[]>(`/api/runs?limit=${limit}${mode ? `&mode=${mode}` : ""}`),
  runDetail: (id: string) => j<any>(`/api/runs/${id}`),
  runTrades: (id: string, status?: "open" | "closed", page = 1, pageSize = 100) =>
    j<{ total: number; items: Trade[] }>(
      `/api/runs/${id}/trades?${status ? `status=${status}&` : ""}page=${page}&page_size=${pageSize}`
    ),
  tradeJournal: (id: string) => j<JournalEvt[]>(`/api/trades/${id}/journal`),
  tradeBarWalk: (id: string) => j<BarWalkRow[]>(`/api/trades/${id}/bar-walk`),
  signalsRecent: (params: {
    run_id?: string;
    status_prefix?: string;
    leg?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params.run_id) q.set("run_id", params.run_id);
    if (params.status_prefix) q.set("status_prefix", params.status_prefix);
    if (params.leg) q.set("leg", params.leg);
    if (params.limit) q.set("limit", String(params.limit));
    return j<SignalRow[]>(`/api/signals/recent?${q.toString()}`);
  },
  funnel: (run_id: string) =>
    j<{ run_id: string; buckets: FunnelBucket[] }>(`/api/signals/funnel?run_id=${run_id}`),
  accountLatest: (run_id: string) =>
    j<{ items: AccountSnap[] }>(`/api/account/latest?run_id=${run_id}`),
  accountSeries: (run_id: string, limit = 500) =>
    j<AccountSnap[]>(`/api/account/series?run_id=${run_id}&limit=${limit}`),
  scanStatus: () => j<{ runs: any[] }>("/api/scan-status"),
};
