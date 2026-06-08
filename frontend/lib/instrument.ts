"use client";
import { createContext, useContext } from "react";

export type Instrument = "gold" | "micro" | "oil" | "oil-micro";

export const INSTRUMENTS = {
  gold: { label: "GOLD MACRO", api: "", color: "#e8c300", symbol: "XAU/USD" },
  micro: { label: "GOLD MICRO", api: "", color: "#ff8c00", symbol: "XAU/USD" },
  oil: { label: "OIL MACRO", api: "", color: "#4fc3f7", symbol: "BCO/USD" },
  "oil-micro": { label: "OIL MICRO", api: "", color: "#26c6da", symbol: "BCO/USD" },
};

export const InstrumentContext = createContext<{
  instrument: Instrument;
  setInstrument: (i: Instrument) => void;
  apiBase: string;
}>({
  instrument: "gold",
  setInstrument: () => {},
  apiBase: INSTRUMENTS.gold.api,
});

export function useInstrument() {
  return useContext(InstrumentContext);
}
