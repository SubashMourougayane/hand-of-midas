"use client";
import useSWR, { type SWRConfiguration } from "swr";
import { client, type ServiceKey } from "@/lib/client";

export function useLatestBacktest<T = unknown>(svc: ServiceKey, config: SWRConfiguration = {}) {
  return useSWR<T>(
    [svc, "backtest", "latest"],
    () => client(svc).latestBacktest<T>(),
    {
      revalidateOnFocus: false,
      ...config,
    },
  );
}
