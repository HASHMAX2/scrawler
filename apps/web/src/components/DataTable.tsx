import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
}

export function DataTable<T>({ columns, rows, onRowClick }: { columns: Column<T>[]; rows: T[]; onRowClick?: (row: T) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {columns.map((c) => (
              <th key={c.key} className={`py-2 px-3 text-xs uppercase tracking-wide text-[var(--text-muted)] font-medium ${c.align === "right" ? "text-right" : "text-left"}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              onClick={() => onRowClick?.(row)}
              className={`border-b border-[var(--border)]/50 transition-colors duration-300 ease-out hover:bg-[var(--accent-soft)] ${onRowClick ? "cursor-pointer" : ""}`}
            >
              {columns.map((c) => (
                <td key={c.key} className={`py-2 px-3 ${c.align === "right" ? "text-right" : "text-left"}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="py-8 text-center text-sm text-[var(--text-muted)]">No rows</div>}
    </div>
  );
}
