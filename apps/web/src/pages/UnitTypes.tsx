import { useQuery } from "@tanstack/react-query";
import { api, type UnitTypeItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ConfidenceBadge, ErrorState, LoadingSkeleton } from "../components/ui";
import { formatAed, formatPct, formatPsf } from "../lib/format";

export function UnitTypes() {
  const { period } = useFilters();
  const { data, isLoading, error } = useQuery({ queryKey: ["unit-types", period], queryFn: () => api.unitTypes(period) });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;

  const columns: Column<UnitTypeItem>[] = [
    { key: "bedroom", header: "Type", render: (r) => <span className="font-medium">{r.bedroom}</span> },
    {
      key: "sales", header: "Sales", align: "right",
      render: (r) => (
        <span className="inline-flex items-center gap-1">
          {r.sales_count.toLocaleString()} <ConfidenceBadge confidence={r.sales_confidence} />
        </span>
      ),
    },
    { key: "sales_share", header: "Sales Share", render: (r) => formatPct(r.sales_share_pct), align: "right" },
    { key: "median_price", header: "Median Price", render: (r) => formatAed(r.median_price), align: "right" },
    { key: "median_psf", header: "PSF", render: (r) => formatPsf(r.median_psf), align: "right" },
    {
      key: "rentals", header: "Rentals", align: "right",
      render: (r) => (
        <span className="inline-flex items-center gap-1">
          {r.rental_count.toLocaleString()} <ConfidenceBadge confidence={r.rental_confidence} />
        </span>
      ),
    },
    { key: "rental_share", header: "Rental Share", render: (r) => formatPct(r.rental_share_pct), align: "right" },
    { key: "median_rent", header: "Median Rent", render: (r) => formatAed(r.median_rent), align: "right" },
    { key: "yield", header: "Est. Gross Yield", render: (r) => (r.estimated_gross_yield_pct !== null ? formatPct(r.estimated_gross_yield_pct) : "N/A"), align: "right" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Unit Type Intelligence</h1>
      <p className="text-xs text-[var(--text-muted)]">
        Are 1BR apartments more liquid than studios? Compare sales & rental demand, pricing, and estimated yield by bedroom type — citywide, this period.
      </p>
      <Card className="p-4">{data && <DataTable columns={columns} rows={data.items} />}</Card>
    </div>
  );
}
