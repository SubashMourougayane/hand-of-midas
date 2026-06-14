"use client";
import { useEffect, useState } from "react";
import { client, type ServiceKey } from "@/lib/client";

interface UseLiveStreamOptions {
  /** Polling interval when SSE is dropped (default 30s). */
  fallbackMs?: number;
}

/**
 * Subscribe to a live state stream. Wraps `MidasClient.streamLive` so React
 * components don't have to manage EventSource / polling lifecycles. Re-opens
 * the connection when the service key changes.
 *
 * Both SSE and the polling fallback hit the hosted API directly via
 * `client.ts`'s API_BASE constant — no Next.js proxy in the path, so
 * streaming responses aren't buffered.
 *
 * Returns:
 * - data: latest snapshot from the server
 * - connected: true once the first SSE event arrives
 * - reconnecting: true while the SSE connection is dropped and retrying
 * - lastUpdate: ISO time string of the most recent payload (for UI staleness)
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
        fallbackMs: opts.fallbackMs,
        onReconnecting: () => setReconnecting(true),
      },
    );
    return unsub;
  }, [svc, opts.fallbackMs]);

  return { data, connected, reconnecting, lastUpdate };
}
