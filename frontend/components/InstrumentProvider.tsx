"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { InstrumentContext, Instrument, INSTRUMENTS } from "@/lib/instrument";

const VALID: Instrument[] = ["micro", "oil-micro"];
const STORAGE_KEY = "midas_system";

// Migrate legacy localStorage entries from retired Macro systems.
const LEGACY_MIGRATIONS: Record<string, Instrument> = {
  gold: "micro",
  oil: "oil-micro",
};

function readInitial(): Instrument {
  if (typeof window === "undefined") return "micro";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored && VALID.includes(stored as Instrument)) return stored as Instrument;
  if (stored && stored in LEGACY_MIGRATIONS) {
    const migrated = LEGACY_MIGRATIONS[stored];
    try { window.localStorage.setItem(STORAGE_KEY, migrated); } catch {}
    return migrated;
  }
  return "micro";
}

export default function InstrumentProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [instrument, setInstrumentState] = useState<Instrument>(readInitial);

  // Hydrate from `?sys=` query param on mount + on URL change.
  useEffect(() => {
    const fromUrl = searchParams.get("sys") as Instrument | null;
    if (fromUrl && VALID.includes(fromUrl) && fromUrl !== instrument) {
      setInstrumentState(fromUrl);
      try { window.localStorage.setItem(STORAGE_KEY, fromUrl); } catch {}
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const setInstrument = useCallback((next: Instrument) => {
    setInstrumentState(next);
    try { window.localStorage.setItem(STORAGE_KEY, next); } catch {}
    // Update URL preserving path + other query params.
    const params = new URLSearchParams(searchParams.toString());
    params.set("sys", next);
    router.replace(`${pathname}?${params.toString()}`);
  }, [router, pathname, searchParams]);

  return (
    <InstrumentContext.Provider value={{
      instrument,
      setInstrument,
      apiBase: INSTRUMENTS[instrument].api,
    }}>
      {children}
    </InstrumentContext.Provider>
  );
}
