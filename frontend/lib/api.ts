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

export async function runBacktest(req: BacktestRequest, apiBase: string, instrument: string = "gold"): Promise<BacktestResult> {
  const prefix = instrument === "oil" ? "oil" : "gold";
  const res = await fetch(`${apiBase}/api/${prefix}/backtest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Backtest failed: ${res.status}`);
  return res.json();
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
  const prefix = instrument === "oil" ? "oil" : "gold";
  const res = await fetch(`${apiBase}/api/${prefix}/backtest/latest`);
  if (!res.ok) return null;
  const data = await res.json();
  return data.result === null ? null : data;
}
