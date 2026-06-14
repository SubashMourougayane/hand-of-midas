"use client";
import { useInstrument } from "@/lib/instrument";
import type { ServiceKey } from "@/lib/client";

/**
 * Returns the active service key + the corresponding MidasClient. Reads from
 * the InstrumentContext, which is fed by URL `?sys=` + localStorage.
 * Use anywhere a hook needs to know which service to query.
 */
export function useSystemParam(): { svc: ServiceKey } {
  const { instrument } = useInstrument();
  return { svc: instrument as ServiceKey };
}
