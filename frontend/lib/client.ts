/**
 * Consolidated API client. One MidasClient per service, keyed by ServiceKey.
 * Replaces the `prefix = instrument === "oil" ? "oil" : ...` ternaries that
 * were duplicated across pages. Auth-aware fetch wrapper auto-attaches
 * Authorization: Bearer ${hom_token} and triggers logout on 401.
 *
 * Used directly by SWR hooks (lib/hooks/*) which provide the React surface.
 * `lib/api.ts` is preserved as a re-export shim during the migration.
 */

export type ServiceKey = "gold" | "micro" | "oil" | "oil-micro";

const TOKEN_KEY = "hom_token";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

function clearTokenAndRedirect() {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(TOKEN_KEY); } catch {}
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

export interface FetchOptions extends RequestInit {
  /** When true, do not redirect to /login on 401 (used by /api/auth/me probe). */
  skipAuthRedirect?: boolean;
}

/**
 * Auth-aware fetch wrapper. Attaches Authorization header when a token is
 * present and clears it on 401. Returns the parsed JSON body or throws ApiError.
 */
export async function authFetch<T = unknown>(url: string, init: FetchOptions = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) {
    if (!init.skipAuthRedirect) clearTokenAndRedirect();
    throw new ApiError(401, "Unauthorized");
  }
  if (!res.ok) {
    let body: unknown = undefined;
    try { body = await res.json(); } catch {}
    throw new ApiError(res.status, `HTTP ${res.status}`, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Build a URL with query parameters, skipping null/undefined values. */
function buildUrl(path: string, params?: Record<string, unknown>): string {
  if (!params) return path;
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === "") continue;
    search.set(k, String(v));
  }
  const qs = search.toString();
  return qs ? `${path}?${qs}` : path;
}

// ── Domain types (re-exported from api.ts to avoid duplication) ─────────────
export type {
  Trade,
  StrategyStats,
  BacktestStats,
  EquityPoint,
  MonthlyPnl,
  YearlyPnl,
  BacktestResult,
  BacktestRequest,
  LatestBacktestResponse,
} from "./api";

// SWR keys are tuples like [serviceKey, "trades", params]. Using arrays makes
// dedup + invalidation natural (mutate(["gold", "trades"]) clears every
// trades-list query).

export interface TradeQuery {
  limit?: number;
  source?: "live" | "backtest";
  page?: number;
  per_page?: number;
}

export interface JournalQuery {
  limit?: number;
  strategy?: string;
  event_type?: string;
  trade_ref?: string;
}

export class MidasClient {
  constructor(public readonly svc: ServiceKey) {}

  private base() {
    return `/api/${this.svc}`;
  }

  // Live state — point-in-time snapshot
  state<T = unknown>() {
    return authFetch<T>(`${this.base()}/state`);
  }

  scanStatus<T = unknown>() {
    return authFetch<T>(`${this.base()}/scan-status`);
  }

  // Trade history — supports `source=live|backtest` plus pagination
  trades<T = unknown>(params: TradeQuery = {}) {
    const path = params.source === "backtest" ? `${this.base()}/trades/backtest` : `${this.base()}/trades`;
    const { source, ...rest } = params;
    return authFetch<T>(buildUrl(path, rest));
  }

  // Journal events
  journal<T = unknown>(params: JournalQuery = {}) {
    return authFetch<T>(buildUrl(`${this.base()}/journal/events`, params as Record<string, unknown>));
  }

  // Latest cached backtest
  latestBacktest<T = unknown>() {
    return authFetch<T>(`${this.base()}/backtest/latest`);
  }

  // Per-trade journey (OHLC + entry/exit metadata)
  journey<T = unknown>(tradeRef: string) {
    return authFetch<T>(buildUrl(`${this.base()}/journey`, { trade_ref: tradeRef }));
  }

  /**
   * Open a live state stream. Uses EventSource (SSE) with polling fallback.
   * Returns an unsubscribe function. The fallback is a 30s setInterval over
   * /state; the SSE consumer also runs the same poll until the first SSE tick
   * arrives, mirroring the prior live page logic.
   */
  streamLive<T = unknown>(onMessage: (data: T) => void, opts: { fallbackMs?: number } = {}): () => void {
    const fallbackMs = opts.fallbackMs ?? 30_000;
    let cancelled = false;
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    const startPolling = () => {
      if (pollTimer || cancelled) return;
      const tick = () => {
        if (cancelled) return;
        this.state<T>()
          .then((data) => { if (!cancelled) onMessage(data); })
          .catch(() => { /* swallow — SSE may recover */ });
      };
      tick();
      pollTimer = setInterval(tick, fallbackMs);
    };

    const stopPolling = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    try {
      es = new EventSource(`${this.base()}/stream`, { withCredentials: false });
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as T;
          stopPolling();
          if (!cancelled) onMessage(data);
        } catch {
          // Ignore malformed events
        }
      };
      es.onerror = () => {
        // Connection dropped; engage polling fallback while the browser retries.
        startPolling();
      };
    } catch {
      // EventSource unsupported in this environment — go straight to polling.
      startPolling();
    }

    return () => {
      cancelled = true;
      es?.close();
      stopPolling();
    };
  }
}

// Convenience factory + cache (clients are stateless, but reusing an instance
// keeps SWR keys referentially stable when needed).
const _cache = new Map<ServiceKey, MidasClient>();

export function client(svc: ServiceKey): MidasClient {
  const hit = _cache.get(svc);
  if (hit) return hit;
  const fresh = new MidasClient(svc);
  _cache.set(svc, fresh);
  return fresh;
}
