"use client";
import { createContext, useContext } from "react";

export type Instrument = "gold" | "oil";

export const INSTRUMENTS = {
  gold: { label: "GOLD", api: "http://localhost:5053", color: "#e8c300", symbol: "XAU/USD" },
  oil: { label: "OIL", api: "http://localhost:5054", color: "#4fc3f7", symbol: "BCO/USD" },
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
