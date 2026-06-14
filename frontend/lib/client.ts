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

  /**
   * Kick off a backtest. The server returns either an SSE stream (Micro
   * services) or a long-polling response (Macro services); we handle both.
   * `onProgress(msg)` receives human-readable progress strings while the
   * job runs. Returns the final BacktestResult after the run completes.
   *
   * Total timeout: 15 minutes (180 × 5s polling cycles).
   */
  async runBacktest<TReq, TRes>(req: TReq, onProgress?: (msg: string) => void): Promise<TRes> {
    const token = getToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;

    const res = await fetch(`${this.base()}/backtest`, {
      method: "POST",
      headers,
      body: JSON.stringify(req),
    });
    if (res.status === 401) {
      clearTokenAndRedirect();
      throw new ApiError(401, "Unauthorized");
    }
    if (!res.ok) throw new ApiError(res.status, `Backtest failed: ${res.status}`);

    const ct = res.headers.get("content-type");
    if (ct?.includes("text/event-stream") && res.body) {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let completed = false;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const text = decoder.decode(value, { stream: true });
          for (const line of text.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.type === "progress" && onProgress) onProgress(payload.message);
              else if (payload.type === "done") completed = true;
              else if (payload.type === "error") throw new Error(payload.message);
            } catch (e) {
              if (e instanceof Error && e.message !== "Unexpected end of JSON input") throw e;
            }
          }
          if (completed) break;
        }
      } catch {
        // SSE disconnected mid-stream — fall through to polling
      }
      if (completed) {
        // DB write may lag the SSE 'done' event by a second or two
        for (let i = 0; i < 10; i++) {
          const latest = await this.latestBacktest<TRes | null>();
          if (latest) return latest;
          await new Promise((r) => setTimeout(r, 3000));
          if (onProgress) onProgress("Saving to database…");
        }
        throw new Error("Backtest completed but results not found in DB");
      }
    }

    // Polling path (Macro services + SSE-fallback)
    if (onProgress) onProgress("Running backtest…");
    for (let i = 0; i < 180; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      if (onProgress) {
        const seconds = (i + 1) * 5;
        onProgress(`Running backtest… (${Math.floor(seconds / 60)}m ${seconds % 60}s elapsed)`);
      }
      const poll = await this.latestBacktest<TRes | null>();
      if (poll) return poll;
    }
    throw new Error("Backtest timed out (15 minutes). Check server logs.");
  }

  // Per-trade journey (OHLC + entry/exit metadata)
  journey<T = unknown>(tradeRef: string) {
    return authFetch<T>(buildUrl(`${this.base()}/journey`, { trade_ref: tradeRef }));
  }

  /**
   * Open a live state stream. Uses EventSource (SSE) with polling fallback.
   * Returns an unsubscribe function. The fallback is a 30s setInterval over
   * /state + /scan-status; the SSE consumer also runs the same poll until
   * the first SSE tick arrives, mirroring the prior live page logic.
   *
   * `baseOverride`: SSE must bypass the Next.js proxy in dev (it buffers
   * streaming responses). Pass a fully-qualified upstream URL prefix here
   * (e.g. https://midas.subashtrades.in) and it'll be used for the
   * EventSource only — the polling fallback continues to use the relative
   * `/api/...` path so it goes through the proxy normally.
   */
  streamLive<T = unknown>(
    onMessage: (data: T) => void,
    opts: { fallbackMs?: number; baseOverride?: string; onReconnecting?: () => void } = {},
  ): () => void {
    const fallbackMs = opts.fallbackMs ?? 30_000;
    let cancelled = false;
    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let connected = false;

    const fallbackBase = `${this.base()}`; // through proxy
    const sseUrl = `${opts.baseOverride ?? ""}${this.base()}/stream`;

    const fallbackFetch = async () => {
      if (cancelled || connected) return;
      try {
        const [s, sc] = await Promise.all([
          fetch(`${fallbackBase}/state`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
          fetch(`${fallbackBase}/scan-status`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
        ]);
        if (cancelled) return;
        const merged: Record<string, unknown> = {};
        if (s) merged.state = s;
        if (sc && !sc.error) merged.scan = sc;
        if (Object.keys(merged).length) onMessage(merged as T);
      } catch {
        /* swallow */
      }
    };

    const startPolling = () => {
      if (pollTimer || cancelled) return;
      fallbackFetch();
      pollTimer = setInterval(fallbackFetch, fallbackMs);
    };
    const stopPolling = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const connectSSE = () => {
      try {
        es = new EventSource(sseUrl);
        es.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data) as T;
            connected = true;
            stopPolling();
            if (!cancelled) onMessage(data);
          } catch {
            /* malformed event */
          }
        };
        es.onerror = () => {
          connected = false;
          opts.onReconnecting?.();
          es?.close();
          es = null;
          // Engage polling while we wait to reconnect
          startPolling();
          if (!cancelled) {
            reconnectTimer = setTimeout(connectSSE, 3000);
          }
        };
      } catch {
        // EventSource unsupported or threw — go straight to polling
        startPolling();
      }
    };

    connectSSE();
    // Initial fetch for fast first paint (SSE takes ~5s for first push)
    fallbackFetch();

    return () => {
      cancelled = true;
      es?.close();
      stopPolling();
      if (reconnectTimer) clearTimeout(reconnectTimer);
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
