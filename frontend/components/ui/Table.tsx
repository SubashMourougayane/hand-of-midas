"use client";
import { ReactNode } from "react";
import { cn } from "./cn";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Cell content. Receives the row + index. */
  cell: (row: T, idx: number) => ReactNode;
  /** Mobile only: short label shown left-of-cell in stacked card mode. Defaults to `header`. */
  mobileLabel?: ReactNode;
  align?: "left" | "right" | "center";
  width?: number | string;
  className?: string;
  /** Hide on mobile stacked card mode (still rendered on desktop). */
  hideOnMobile?: boolean;
}

interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, idx: number) => string | number;
  /** Per-row click handler. Renders rows as buttons when set. */
  onRowClick?: (row: T, idx: number) => void;
  emptyState?: ReactNode;
  loading?: boolean;
  loadingRows?: number;
  stickyHeader?: boolean;
  dense?: boolean;
  className?: string;
}

const ALIGN: Record<NonNullable<Column<unknown>["align"]>, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  emptyState,
  loading,
  loadingRows = 6,
  stickyHeader = true,
  dense = false,
  className,
}: TableProps<T>) {
  return (
    <div className={cn("w-full", className)}>
      {/* Desktop: real table */}
      <div className="hidden md:block overflow-auto">
        <table className="w-full border-collapse">
          <thead
            className={cn(
              stickyHeader && "sticky top-0 z-10 bg-[var(--color-surface-1)]",
            )}
          >
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  style={{ width: col.width }}
                  className={cn(
                    "border-b border-[var(--color-border)]",
                    "text-[10px] font-semibold uppercase tracking-[0.6px] text-[var(--color-text-muted)]",
                    "px-3 py-2",
                    ALIGN[col.align ?? "left"],
                    col.className,
                  )}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: loadingRows }).map((_, i) => (
                  <tr key={`sk-${i}`} className="border-b border-[var(--color-border)]/60">
                    {columns.map((col) => (
                      <td key={col.key} className={cn("px-3", dense ? "py-1.5" : "py-2.5")}>
                        <div className="h-3 bg-[var(--color-surface-2)] rounded-[3px] animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.length === 0
                ? null
                : rows.map((row, idx) => {
                    const key = rowKey(row, idx);
                    const Tag = onRowClick ? "tr" : "tr";
                    return (
                      <Tag
                        key={key}
                        onClick={onRowClick ? () => onRowClick(row, idx) : undefined}
                        className={cn(
                          "border-b border-[var(--color-border)]/60",
                          onRowClick && "cursor-pointer hover:bg-[var(--color-surface-2)] transition-colors",
                        )}
                      >
                        {columns.map((col) => (
                          <td
                            key={col.key}
                            className={cn(
                              "px-3 text-[12px] text-[var(--color-text)]",
                              dense ? "py-1.5" : "py-2.5",
                              ALIGN[col.align ?? "left"],
                              col.className,
                            )}
                          >
                            {col.cell(row, idx)}
                          </td>
                        ))}
                      </Tag>
                    );
                  })}
          </tbody>
        </table>
        {!loading && rows.length === 0 && emptyState ? (
          <div className="py-10 flex items-center justify-center">{emptyState}</div>
        ) : null}
      </div>

      {/* Mobile: stacked cards */}
      <div className="md:hidden flex flex-col gap-2">
        {loading
          ? Array.from({ length: loadingRows }).map((_, i) => (
              <div
                key={`m-sk-${i}`}
                className="rounded-[6px] border border-[var(--color-border)] bg-[var(--color-surface-1)] p-3"
              >
                <div className="h-3 bg-[var(--color-surface-2)] rounded-[3px] animate-pulse mb-2" />
                <div className="h-3 w-2/3 bg-[var(--color-surface-2)] rounded-[3px] animate-pulse" />
              </div>
            ))
          : rows.length === 0
            ? emptyState
              ? <div className="py-8 flex items-center justify-center">{emptyState}</div>
              : null
            : rows.map((row, idx) => {
                const key = rowKey(row, idx);
                const visible = columns.filter((c) => !c.hideOnMobile);
                return (
                  <button
                    key={key}
                    onClick={onRowClick ? () => onRowClick(row, idx) : undefined}
                    disabled={!onRowClick}
                    className={cn(
                      "text-left w-full rounded-[6px] p-3",
                      "bg-[var(--color-surface-1)] border border-[var(--color-border)]",
                      onRowClick && "active:bg-[var(--color-surface-2)] transition-colors",
                      "disabled:cursor-default",
                    )}
                  >
                    <div className="flex flex-col gap-1.5">
                      {visible.map((col) => (
                        <div
                          key={col.key}
                          className="flex items-baseline justify-between gap-3 text-[12px]"
                        >
                          <span className="text-[10px] uppercase tracking-[0.6px] text-[var(--color-text-muted)] font-medium">
                            {col.mobileLabel ?? col.header}
                          </span>
                          <span className="text-[var(--color-text)] text-right">
                            {col.cell(row, idx)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </button>
                );
              })}
      </div>
    </div>
  );
}
