// WebSocket hook with auto-reconnect.
import { useEffect, useRef, useState } from "react";

export type WsEnvelope = {
  channel: "journal" | "signal" | "trade" | "account" | "account_live" | "price" | "positions_live" | "hello" | "pong";
  run_id: string | null;
  ts: string;
  payload: Record<string, unknown>;
};

export type WsStatus = "connecting" | "open" | "closed";

export function useWsLive(runId?: string | null) {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const [lastMessageAt, setLastMessageAt] = useState<number>(0);
  const listeners = useRef<Set<(env: WsEnvelope) => void>>(new Set());
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let mounted = true;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${location.host}/ws/live${runId ? `?run_id=${runId}` : ""}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus("connecting");

      ws.addEventListener("open", () => {
        if (!mounted) return;
        setStatus("open");
      });
      ws.addEventListener("message", (ev) => {
        if (!mounted) return;
        setLastMessageAt(Date.now());
        try {
          const env: WsEnvelope = JSON.parse(ev.data);
          listeners.current.forEach((fn) => fn(env));
        } catch {
          /* ignore */
        }
      });
      ws.addEventListener("close", () => {
        if (!mounted) return;
        setStatus("closed");
        wsRef.current = null;
        reconnectTimer = setTimeout(connect, 2000);
      });
      ws.addEventListener("error", () => {
        try { ws.close(); } catch { /* */ }
      });
    };

    connect();

    return () => {
      mounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) {
        try { wsRef.current.close(); } catch { /* */ }
      }
    };
  }, [runId]);

  const onMessage = (fn: (env: WsEnvelope) => void): (() => void) => {
    listeners.current.add(fn);
    return () => {
      listeners.current.delete(fn);
    };
  };

  return { status, lastMessageAt, onMessage };
}
