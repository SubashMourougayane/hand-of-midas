"use client";
import useSWR, { type SWRConfiguration } from "swr";
import { client, type ServiceKey } from "@/lib/client";

export function useScanStatus<T = unknown>(svc: ServiceKey, config: SWRConfiguration = {}) {
  return useSWR<T>(
    [svc, "scan-status"],
    () => client(svc).scanStatus<T>(),
    {
      refreshInterval: 5_000,
      revalidateOnFocus: true,
      ...config,
    },
  );
}
