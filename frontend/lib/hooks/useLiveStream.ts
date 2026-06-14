"use client";
import { useEffect, useState } from "react";
import { client, type ServiceKey } from "@/lib/client";

interface UseLiveStreamOptions {
  /** Override the SSE URL prefix (used in dev to bypass the Next proxy). */
  baseOverride?: string;
  /** Polling interval when SSE is dropped (default 30s). */
  fallbackMs?: number;
}

/**
 * Subscribe to a live state stream. Wraps `MidasClient.streamLive` so React
 * components don't have to manage EventSource / polling lifecycles. Re-opens
 * the connection when the service key changes.
 *
 * Returns:
 * - data: latest snapshot from the server
 * - connected: true once the first SSE event arrives
 * - reconnecting: true while the SSE connection is dropped and retrying
 * - lastUpdate: ISO time string of the most recent payload (for UI staleness)
 *
 * NOT an SWR hook — SSE is a subscription, not a request/response cycle.
 */
export function useLiveStream<T = unknown>(svc: ServiceKey, opts: UseLiveStreamOptions = {}) {
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  useEffect(() => {
    setData(null);
    setConnected(false);
    setReconnecting(false);
    setLastUpdate("");
    const unsub = client(svc).streamLive<T>(
      (next) => {
        setData(next);
        setConnected(true);
        setReconnecting(false);
        setLastUpdate(new Date().toISOString());
      },
      {
        baseOverride: opts.baseOverride,
        fallbackMs: opts.fallbackMs,
        onReconnecting: () => setReconnecting(true),
      },
    );
    return unsub;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [svc, opts.baseOverride, opts.fallbackMs]);

  return { data, connected, reconnecting, lastUpdate };
}
