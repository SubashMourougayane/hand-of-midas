import { ReactNode } from "react";
import { JournalEvt } from "../lib/api";
import { bgForGateStatus, colorForGateStatus, fmtTime } from "../lib/format";

// Keys we hide entirely — redundant with the row's own timestamp/label, or noise.
const HIDDEN_KEYS = new Set([
  "bar_ts",
  "seq",
  "ts",
  "event_type",
  "symbol",
  "contract_size",
]);

// Format a scalar value compactly. Objects/arrays are handled separately
// (never string-concatenated — that was the `[object Object]` bug).
function fmtScalar(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v)
      ? String(v)
      : v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

function KVChip({ k, v }: { k: string; v: unknown }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-ds-sm border border-line-subtle bg-bg-elevated px-1.5 py-0.5 text-ds-xs">
      <span className="text-ink-muted">{k}</span>
      <span className="font-mono text-ink-secondary max-w-[14rem] truncate">
        {fmtScalar(v)}
      </span>
    </span>
  );
}

// Render a flat key-value block for a nested object (e.g. `extra`), one chip
// per key. Hidden/noise keys are dropped. Nested-nested objects fall back to
// a compact chip with a title tooltip.
function ObjectBlock({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj).filter(([k]) => !HIDDEN_KEYS.has(k));
  if (entries.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {entries.map(([k, v]) => {
        if (v != null && typeof v === "object") {
          let title = "";
          try {
            title = JSON.stringify(v);
          } catch {
            title = String(v);
          }
          return (
            <span
              key={k}
              title={title}
              className="inline-flex items-center gap-1 rounded-ds-sm border border-line-subtle bg-bg-elevated px-1.5 py-0.5 text-ds-xs"
            >
              <span className="text-ink-muted">{k}</span>
              <span className="font-mono text-ink-dim">{"{…}"}</span>
            </span>
          );
        }
        return <KVChip key={k} k={k} v={v} />;
      })}
    </div>
  );
}

function DetailBlock({ detail }: { detail: Record<string, unknown> }) {
  const entries = Object.entries(detail).filter(([k]) => !HIDDEN_KEYS.has(k));
  if (entries.length === 0) return null;

  // Split scalars (rendered as chips inline) from nested objects (flattened
  // into their own labelled key-value blocks — this is where `extra` lands).
  const scalars = entries.filter(([, v]) => v == null || typeof v !== "object");
  const objects = entries.filter(([, v]) => v != null && typeof v === "object");

  return (
    <div className="mt-1 space-y-1.5">
      {scalars.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {scalars.map(([k, v]) => (
            <KVChip key={k} k={k} v={v} />
          ))}
        </div>
      )}
      {objects.map(([k, v]) => (
        <div key={k} className="space-y-1">
          <div className="text-ds-xs uppercase tracking-wide text-ink-dim">{k}</div>
          <ObjectBlock obj={v as Record<string, unknown>} />
        </div>
      ))}
    </div>
  );
}

// Human label for an event type.
function eventLabel(t: string): string {
  return t.replace(/_/g, " ");
}

// A small glyph per event family — keeps the timeline visually scannable.
function eventIcon(t: string): string {
  if (t === "ENTRY_FILL" || t === "ENTRY_SUBMIT") return "▸";
  if (t === "PARTIAL_TP_APPLIED") return "½";
  if (t === "EXIT_TP") return "✓";
  if (t === "EXIT_SL") return "✕";
  if (t === "EXIT_TIMEOUT") return "⏱";
  if (t === "OPEN_STATE") return "●";
  if (t.startsWith("GATE_")) return "◆";
  return "•";
}

// A synthetic "current state" pseudo-event injected for OPEN trades.
export type SyntheticEvt = {
  synthetic: true;
  ts: string;
  event_type: string;
  detail: Record<string, unknown>;
};

type Row = JournalEvt | SyntheticEvt;

function isSynthetic(e: Row): e is SyntheticEvt {
  return (e as SyntheticEvt).synthetic === true;
}

export function EventTimeline({
  events,
  synthetic,
}: {
  events: JournalEvt[];
  synthetic?: SyntheticEvt | null;
}) {
  if (events.length === 0 && !synthetic) {
    return (
      <div className="px-3 py-10 text-center text-ink-muted text-ds-sm">
        No journal events for this trade.
      </div>
    );
  }

  const sorted: JournalEvt[] = [...events].sort((a, b) => {
    const t = new Date(a.ts).getTime() - new Date(b.ts).getTime();
    if (t !== 0) return t;
    return a.event_id - b.event_id;
  });

  // Synthetic "now" row goes last (most recent).
  const rows: Row[] = synthetic ? [...sorted, synthetic] : sorted;

  return (
    <ol className="my-2 px-2 space-y-1.5">
      {rows.map((e, idx) => {
        const dot = bgForGateStatus(e.event_type);
        const key = isSynthetic(e) ? `syn-${idx}` : `evt-${e.event_id}`;
        const pulse = isSynthetic(e) ? "animate-ds-pulse" : "";
        return (
          <li
            key={key}
            className="relative rounded-ds border border-line-subtle bg-bg-base/40 pl-3 pr-2 py-2 group"
            style={{ borderLeft: `3px solid ${dot}` }}
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-ds-sm leading-none ${pulse}`} style={{ color: dot }}>
                {eventIcon(e.event_type)}
              </span>
              <span
                className={`text-ds-sm font-medium uppercase tracking-tight ${colorForGateStatus(
                  e.event_type
                )}`}
              >
                {eventLabel(e.event_type)}
              </span>
              <span className="ml-auto font-mono text-ds-xs text-ink-muted tabular-nums">
                {fmtTime(e.ts)}
              </span>
            </div>
            <DetailBlock detail={e.detail || {}} />
          </li>
        );
      })}
    </ol>
  );
}

// Re-export helper for callers that want to render an icon standalone.
export function EventGlyph({ type }: { type: string }): ReactNode {
  return eventIcon(type);
}
