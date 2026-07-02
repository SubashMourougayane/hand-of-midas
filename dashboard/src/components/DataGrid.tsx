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
  return (
    <table className="w-full text-ds-sm">
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
            <td
              colSpan={columns.length}
              className="px-3 py-10 text-center text-ink-muted"
            >
              {empty}
            </td>
          </tr>
        )}
        {rows.map((r, ri) => {
          const k = rowKey ? rowKey(r, ri) : String(ri);
          const flash =
            flashRowKey && k === flashRowKey
              ? flashTone === "bull"
                ? "animate-ds-flash-bull"
                : "animate-ds-flash-bear"
              : "";
          return (
            <tr
              key={k}
              className={`
                border-b border-line-subtle
                hover:bg-bg-elevated transition-colors duration-ds
                ${onRowClick ? "cursor-pointer" : ""}
                ${flash}
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
  );
}
