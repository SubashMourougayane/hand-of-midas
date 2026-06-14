"use client";
import { useEffect, useRef, useState } from "react";
import { client, type ServiceKey } from "@/lib/client";

/**
 * Subscribe to a live state stream. Wraps `MidasClient.streamLive` so React
 * components don't have to manage EventSource / polling lifecycles. Re-opens
 * the connection when the service key changes. Returns the latest snapshot
 * plus a `connected` flag that flips after the first event arrives.
 *
 * NOT an SWR hook — SSE is a subscription, not a request/response cycle.
 */
export function useLiveStream<T = unknown>(svc: ServiceKey) {
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const errorRef = useRef<unknown>(null);

  useEffect(() => {
    setData(null);
    setConnected(false);
    errorRef.current = null;
    const unsub = client(svc).streamLive<T>((next) => {
      setData(next);
      setConnected(true);
    });
    return unsub;
  }, [svc]);

  return { data, connected, error: errorRef.current };
}
