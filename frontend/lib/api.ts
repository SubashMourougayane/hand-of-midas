export interface Trade {
  date: string;
  year: number;
  month: number;
  strategy: string;
  direction: string;
  entry: number;
  sl: number;
  tp: number;
  exit_price: number;
  pnl_unit: number;
  pnl_sized: number;
  units: number;
  status: string;
  bars_held: number;
  hold_human: string;
  risk: number;
  r_mult: number;
  equity_after: number;
}

export interface StrategyStats {
  trades: number;
  wins: number;
  wr: number;
  pf: number;
  pnl: number;
}

export interface BacktestStats {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  profit_factor: number;
  total_pnl: number;
  max_drawdown_pct: number;
  avg_win: number;
  avg_loss: number;
  risk_reward: number;
  trades_per_year: number;
  months: number;
  strategies: Record<string, StrategyStats>;
  sessions?: Record<string, { trades: number; wins: number; win_rate: number; pnl: number; pf: number; monthly: number }>;
}

export interface EquityPoint {
  date: string;
  pnl: number;
  equity: number;
}

export interface MonthlyPnl {
  month: string;
  pnl: number;
}

export interface YearlyPnl {
  year: number;
  trades: number;
  wins: number;
  pnl: number;
  wr: number;
  return_pct: number;
  start_fund: number;
  end_fund: number;
}

export interface BacktestResult {
  stats: BacktestStats;
  trades: Trade[];
  equity_curve: EquityPoint[];
  monthly_pnl: MonthlyPnl[];
  yearly_pnl: YearlyPnl[];
  duration_ms: number;
}

export interface BacktestRequest {
  strategies: string[];
  start_date: string;
  end_date: string;
  capital: number;
  risk_pct: number;
}

export const API_BASE_GOLD = "";
export const API_BASE_OIL = "";

export async function runBacktest(
  req: BacktestRequest,
  apiBase: string,
  instrument: string = "gold",
  onProgress?: (msg: string) => void,
): Promise<BacktestResult> {
  const prefix = instrument === "oil" ? "oil" : instrument === "micro" ? "micro" : "gold";
  const res = await fetch(`${apiBase}/api/${prefix}/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Backtest failed: ${res.status}`);

  // Both Macro and Micro now run in background threads.
  // Try SSE first (Micro), fall back to polling (both).
  if (res.headers.get("content-type")?.includes("text/event-stream")) {
    const reader = res.body?.getReader();
    if (reader) {
      const decoder = new TextDecoder();
      let completed = false;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const text = decoder.decode(value, { stream: true });
          for (const line of text.split("\n")) {
            if (line.startsWith("data: ")) {
              try {
                const payload = JSON.parse(line.slice(6));
                if (payload.type === "progress" && onProgress) onProgress(payload.message);
                else if (payload.type === "done") completed = true;
                else if (payload.type === "error") throw new Error(payload.message);
              } catch (e) {
                if (e instanceof Error && e.message !== "Unexpected end of JSON input") throw e;
              }
            }
          }
          if (completed) break;
        }
      } catch {
        // SSE disconnected — fall through to polling
      }
      if (completed) {
        // Load from DB (retry for save to complete)
        for (let i = 0; i < 10; i++) {
          const latest = await getLatestBacktest(apiBase, instrument);
          if (latest) return latest as unknown as BacktestResult;
          await new Promise(r => setTimeout(r, 3000));
          if (onProgress) onProgress("Saving to database...");
        }
        throw new Error("Backtest completed but results not found in DB");
      }
    }
  }

  // Poll for results (works for both Macro and Micro)
  if (onProgress) onProgress("Running backtest...");
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 5000));
    if (onProgress) onProgress(`Running backtest... (${(i + 1) * 5}s elapsed)`);
    const poll = await getLatestBacktest(apiBase, instrument);
    if (poll) return poll as unknown as BacktestResult;
  }
  throw new Error("Backtest timed out (5 minutes). Check server logs.");
}

export interface LatestBacktestResponse {
  stats: BacktestStats;
  trades: Trade[];
  equity_curve: EquityPoint[];
  monthly_pnl: MonthlyPnl[];
  yearly_pnl: YearlyPnl[];
  duration_ms: number;
  config: BacktestRequest;
  created_at: string;
}

export async function getLatestBacktest(apiBase: string, instrument: string = "gold"): Promise<LatestBacktestResponse | null> {
  const prefix = instrument === "oil" ? "oil" : instrument === "micro" ? "micro" : "gold";
  const res = await fetch(`${apiBase}/api/${prefix}/backtest/latest`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.result === null ? null : data;
}
