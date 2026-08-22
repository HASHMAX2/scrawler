import { useQuery } from "@tanstack/react-query";
import { api, type DeveloperListItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ErrorState, LoadingSkeleton } from "../components/ui";
import { formatAed, formatPct } from "../lib/format";

export function Developers() {
  const { period } = useFilters();
  const { data, isLoading, error } = useQuery({ queryKey: ["developers", period], queryFn: () => api.developers(period, 50) });

  const columns: Column<DeveloperListItem>[] = [
    { key: "name", header: "Developer", render: (r) => r.name },
    { key: "projects", header: "Projects (scraped)", render: (r) => r.project_count.toLocaleString(), align: "right" },
    { key: "sales_count", header: "Sales (matched)", render: (r) => r.sales_count.toLocaleString(), align: "right" },
    { key: "sales_value", header: "Sales Value", render: (r) => formatAed(r.sales_value), align: "right" },
    { key: "share", header: "Market Share", render: (r) => (r.market_share_pct !== null ? formatPct(r.market_share_pct) : "N/A"), align: "right" },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Developers</h1>
      <p className="text-xs text-[var(--text-muted)]">
        Sales figures only cover DLD transactions matched to a scraped development/developer — currently ~3% of projects. Most developer sales
        activity is not yet attributable; see Data Quality for coverage.
      </p>
      {isLoading && <LoadingSkeleton rows={8} />}
      {error && <ErrorState message={(error as Error).message} />}
      {data && <Card className="p-4"><DataTable columns={columns} rows={data.items} /></Card>}
    </div>
  );
}
