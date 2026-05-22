"use client";
import { useState } from "react";
import { InstrumentContext, Instrument, INSTRUMENTS } from "@/lib/instrument";

export default function InstrumentProvider({ children }: { children: React.ReactNode }) {
  const [instrument, setInstrument] = useState<Instrument>("gold");

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
