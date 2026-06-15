"use client";
import useSWR, { type SWRConfiguration } from "swr";
import { client, type ServiceKey, type TradeQuery } from "@/lib/client";

/**
 * SWR-backed trade list. Source = "live" or "backtest". Auto-revalidates on
 * focus; the previous polling interval pattern is replaced by the configured
 * `refreshInterval` (default 15s for live, no polling for backtest).
 */
export function useTrades<T = unknown>(
  svc: ServiceKey,
  params: TradeQuery = {},
  config: SWRConfiguration = {},
) {
  const isLive = params.source !== "backtest";
  return useSWR<T>(
    [svc, "trades", params],
    () => client(svc).trades<T>(params),
    {
      refreshInterval: isLive ? 15_000 : 0,
      revalidateOnFocus: true,
      ...config,
    },
  );
}
