import { ReactNode } from "react";

export type Column<T> = {
  header: ReactNode;
  cell: (row: T, idx: number) => ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
  className?: string;
};

export function DataGrid<T>({
  columns,
  rows,
  empty = "No data",
  onRowClick,
  rowKey,
  flashRowKey,
  flashTone = "bull",
}: {
  columns: Column<T>[];
  rows: T[];
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  rowKey?: (row: T, idx: number) => string;
  flashRowKey?: string | null;
  flashTone?: "bull" | "bear";
}) {
  const flashCls = (k: string) =>
    flashRowKey && k === flashRowKey
      ? flashTone === "bull"
        ? "animate-ds-flash-bull"
        : "animate-ds-flash-bear"
      : "";

  return (
    <>
      {/* ── Desktop (md+): the dense table. ── */}
      <div className="hidden md:block w-full overflow-x-auto scroll-slim">
        <table className="w-full min-w-[820px] text-ds-sm">
          <thead className="sticky top-0 z-10 bg-glass-strong backdrop-blur-md">
            <tr className="text-ink-muted text-ds-xs uppercase tracking-wide border-b border-glass-border">
              {columns.map((c, i) => (
                <th
                  key={i}
                  className={`px-3 py-2 font-medium ${
                    c.align === "right"
                      ? "text-right"
                      : c.align === "center"
                      ? "text-center"
                      : "text-left"
                  } ${c.className ?? ""}`}
                  style={c.width ? { width: c.width } : undefined}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-10 text-center text-ink-muted">
                  {empty}
                </td>
              </tr>
            )}
            {rows.map((r, ri) => {
              const k = rowKey ? rowKey(r, ri) : String(ri);
              return (
                <tr
                  key={k}
                  className={`
                    border-b border-line-subtle
                    hover:bg-glass transition-colors duration-ds
                    ${onRowClick ? "cursor-pointer" : ""}
                    ${flashCls(k)}
                  `}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                >
                  {columns.map((c, ci) => (
                    <td
                      key={ci}
                      className={`px-3 py-2 ${
                        c.align === "right"
                          ? "text-right"
                          : c.align === "center"
                          ? "text-center"
                          : "text-left"
                      } ${c.className ?? ""}`}
                    >
                      {c.cell(r, ri)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ── Mobile (<md): each row reflows to a stacked glass card. Same column
             config drives both — header = field label, cell = value. Columns
             with an empty header render full-width (the "hero" row, e.g. status
             + symbol). No horizontal-scroll trap. ── */}
      <div className="md:hidden flex flex-col gap-2">
        {rows.length === 0 && (
          <div className="px-3 py-10 text-center text-ink-muted">{empty}</div>
        )}
        {rows.map((r, ri) => {
          const k = rowKey ? rowKey(r, ri) : String(ri);
          return (
            <div
              key={k}
              className={`glass rounded-ds-lg p-3 flex flex-col gap-1.5 ${
                onRowClick ? "cursor-pointer active:bg-glass-strong" : ""
              } ${flashCls(k)}`}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
            >
              {columns.map((c, ci) => {
                const hasLabel =
                  c.header !== null && c.header !== undefined && c.header !== "";
                return (
                  <div
                    key={ci}
                    className="flex items-center justify-between gap-3 min-w-0"
                  >
                    {hasLabel && (
                      <span className="text-ds-xs uppercase tracking-wide text-ink-muted shrink-0">
                        {c.header}
                      </span>
                    )}
                    <span
                      className={`min-w-0 ${hasLabel ? "text-right" : "flex-1"} ${
                        c.className ?? ""
                      }`}
                    >
                      {c.cell(r, ri)}
                    </span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </>
  );
}
