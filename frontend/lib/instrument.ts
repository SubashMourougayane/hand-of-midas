"use client";
import { createContext, useContext } from "react";

// Macros (Gold + Oil Macro) retired 2026-06-19 — see start-win.bat header
// and DECISION_2026-06-19_DROP_MACROS.md.
export type Instrument = "micro" | "oil-micro";

export const INSTRUMENTS = {
  micro: { label: "GOLD MICRO", api: "", color: "#ff8c00", symbol: "XAU/USD" },
  "oil-micro": { label: "OIL MICRO", api: "", color: "#26c6da", symbol: "BCO/USD" },
};

export const InstrumentContext = createContext<{
  instrument: Instrument;
  setInstrument: (i: Instrument) => void;
  apiBase: string;
}>({
  instrument: "micro",
  setInstrument: () => {},
  apiBase: INSTRUMENTS.micro.api,
});

export function useInstrument() {
  return useContext(InstrumentContext);
}
