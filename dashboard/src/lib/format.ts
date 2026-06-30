import { format as fnsFormat, parseISO } from "date-fns";

export const fmtPrice = (v?: number | null, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(digits);

export const fmtR = (v?: number | null, digits = 2) => {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  return v >= 0 ? `+${s}` : s;
};

export const fmtPct = (v?: number | null, digits = 2) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const fmtTs = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return fnsFormat(parseISO(iso), "yyyy-MM-dd HH:mm:ss");
  } catch {
    return iso;
  }
};

export const fmtTime = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return fnsFormat(parseISO(iso), "HH:mm:ss");
  } catch {
    return iso;
  }
};

export const colorForR = (v?: number | null): string => {
  if (v == null) return "text-term-gray";
  if (v > 0) return "text-term-green";
  if (v < 0) return "text-term-red";
  return "text-term-gray";
};

export const colorForGateStatus = (status: string): string => {
  if (status === "GATE_SIGNAL_PASSED") return "text-term-green";
  if (status.startsWith("GATE_PIVOT") || status.startsWith("GATE_SETUP_BUILT"))
    return "text-term-cyan";
  if (status.startsWith("GATE_")) return "text-term-red";
  if (status === "ENTRY_FILL" || status === "EXIT_TP") return "text-term-green";
  if (status === "EXIT_SL") return "text-term-red";
  return "text-term-amber";
};
