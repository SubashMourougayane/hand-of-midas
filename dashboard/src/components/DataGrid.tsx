import { ReactNode } from "react";

export type Column<T> = {
  header: ReactNode;
  cell: (row: T, idx: number) => ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
};

export function DataGrid<T>({
  columns,
  rows,
  empty = "no data",
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
}) {
  return (
    <table className="w-full text-term-sm">
      <thead className="sticky top-0 bg-term-bg z-10">
        <tr className="text-term-amberDim text-term-xs uppercase border-b border-term-amberDim">
          {columns.map((c, i) => (
            <th
              key={i}
              className={`px-2 py-1 font-normal ${c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left"}`}
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
              className="px-2 py-4 text-center text-term-textMuted"
            >
              {empty}
            </td>
          </tr>
        )}
        {rows.map((r, ri) => (
          <tr
            key={ri}
            className={`border-b border-term-panel hover:bg-term-panel ${
              onRowClick ? "cursor-pointer" : ""
            }`}
            onClick={onRowClick ? () => onRowClick(r) : undefined}
          >
            {columns.map((c, ci) => (
              <td
                key={ci}
                className={`px-2 py-1 ${c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left"}`}
              >
                {c.cell(r, ri)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
