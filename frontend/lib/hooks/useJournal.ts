"use client";
import useSWR, { type SWRConfiguration } from "swr";
import { client, type ServiceKey, type JournalQuery } from "@/lib/client";

export function useJournal<T = unknown>(
  svc: ServiceKey,
  params: JournalQuery = {},
  config: SWRConfiguration = {},
) {
  return useSWR<T>(
    [svc, "journal", params],
    () => client(svc).journal<T>(params),
    {
      refreshInterval: 30_000,
      revalidateOnFocus: true,
      ...config,
    },
  );
}
