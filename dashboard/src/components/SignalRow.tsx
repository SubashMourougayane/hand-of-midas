import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { SignalRow as SignalRowT } from "../lib/api";
import { colorForGateStatus, fmtTime } from "../lib/format";
import { gateLabel, legName } from "../lib/labels";
import { Pill } from "./Pill";
import { GateChecklist } from "./GateChecklist";

function gateTone(status: string): "bull" | "bear" | "info" | "warn" | "neutral" {
  if (status === "GATE_SIGNAL_PASSED" || status === "ENTRY_FILL" || status === "EXIT_TP")
    return "bull";
  if (status.startsWith("GATE_PIVOT") || status.startsWith("GATE_SETUP_BUILT"))
    return "info";
  if (status === "EXIT_TIMEOUT") return "warn";
  if (status.startsWith("GATE_") || status === "EXIT_SL") return "bear";
  return "neutral";
}

export function SignalRowItem({
  signal,
  isNew = false,
  expandable = false,
}: {
  signal: SignalRowT;
  isNew?: boolean;
  expandable?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const tone = gateTone(signal.status);
  const detail = signal.detail || {};
  const leg = detail.leg as string | undefined;
  return (
    <div
      className={`
        border-b border-line-subtle
        ${isNew ? (tone === "bull" ? "animate-ds-flash-bull" : tone === "bear" ? "animate-ds-flash-bear" : "") : ""}
      `}
    >
      <button
        type="button"
        onClick={expandable ? () => setOpen((x) => !x) : undefined}
        className={`
          group w-full text-left flex items-center gap-3 px-3 py-1.5
          hover:bg-bg-elevated transition-colors duration-ds
          ${expandable ? "cursor-pointer" : "cursor-default"}
        `}
      >
        {expandable && (
          <span className="shrink-0 text-ink-muted">
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        )}
        <span className="font-mono text-ds-xs text-ink-muted w-16 shrink-0">
          {fmtTime(signal.ts)}
        </span>
        <Pill tone={tone} className="shrink-0">
          {gateLabel(signal.status)}
        </Pill>
        {leg && (
          <span className="text-ds-xs text-ink-secondary shrink-0">
            {legName(leg)}
          </span>
        )}
        {signal.reason && (
          <span className="text-ds-xs text-ink-muted truncate flex-1">
            {signal.reason}
          </span>
        )}
        {!signal.reason && <span className="flex-1" />}
        {signal.zone_id != null && (
          <span className="font-mono text-ds-xs text-ink-muted shrink-0">
            z{signal.zone_id}
          </span>
        )}
      </button>
      {expandable && open && (
        <div className="border-t border-line-subtle bg-bg-base/40">
          <GateChecklist eventType={signal.status} detail={detail as any} />
        </div>
      )}
    </div>
  );
}
