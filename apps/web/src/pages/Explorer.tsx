import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type RentalRow, type SaleRow } from "../lib/api";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ErrorState, LoadingSkeleton, Select } from "../components/ui";
import { formatAed } from "../lib/format";

export function Explorer() {
  const [dataset, setDataset] = useState<"sales" | "rentals">("sales");
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const sales = useQuery({
    queryKey: ["explorer-sales", page],
    queryFn: () => api.explorerSales(page, pageSize, {}),
    enabled: dataset === "sales",
  });
  const rentals = useQuery({
    queryKey: ["explorer-rentals", page],
    queryFn: () => api.explorerRentals(page, pageSize, {}),
    enabled: dataset === "rentals",
  });

  const saleColumns: Column<SaleRow>[] = [
    { key: "date", header: "Date", render: (r) => r.instance_date },
    { key: "community", header: "Community", render: (r) => r.community },
    { key: "project", header: "Project", render: (r) => r.project ?? "—" },
    { key: "type", header: "Type", render: (r) => r.property_type },
    { key: "bedroom", header: "Bedroom", render: (r) => r.bedroom ?? "—" },
    { key: "price", header: "Price", render: (r) => formatAed(r.price), align: "right" },
    { key: "psf", header: "PSF", render: (r) => (r.price_per_sqft ? r.price_per_sqft.toFixed(0) : "—"), align: "right" },
    { key: "offplan", header: "Off-Plan", render: (r) => (r.is_offplan ? "Yes" : "No") },
  ];

  const rentalColumns: Column<RentalRow>[] = [
    { key: "date", header: "Date", render: (r) => r.registration_date },
    { key: "community", header: "Community", render: (r) => r.community },
    { key: "project", header: "Project", render: (r) => r.project ?? "—" },
    { key: "type", header: "Type", render: (r) => r.property_type },
    { key: "bedroom", header: "Bedroom", render: (r) => r.bedroom ?? "—" },
    { key: "rent", header: "Annual Rent", render: (r) => formatAed(r.annual_rent), align: "right" },
    { key: "renewal", header: "Renewal", render: (r) => (r.is_renewal ? "Yes" : "No") },
  ];

  const active = dataset === "sales" ? sales : rentals;

  const downloadCsv = () => {
    const items = (dataset === "sales" ? sales.data?.items : rentals.data?.items) ?? [];
    if (items.length === 0) return;
    const keys = Object.keys(items[0] as object);
    const csv = [keys.join(","), ...items.map((row) => keys.map((k) => JSON.stringify((row as Record<string, unknown>)[k] ?? "")).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${dataset}-page${page}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Data Explorer</h1>
        <div className="flex items-center gap-2">
          <button onClick={downloadCsv} className="text-xs border border-[var(--border)] rounded px-3 py-1.5 hover:bg-[var(--hover-overlay)]">Download CSV (this page)</button>
          <Select value={dataset} onChange={(v) => { setDataset(v as "sales" | "rentals"); setPage(1); }} options={[{ value: "sales", label: "Sales" }, { value: "rentals", label: "Rentals" }]} />
        </div>
      </div>
      {active.isLoading && <LoadingSkeleton rows={8} />}
      {active.error && <ErrorState message={(active.error as Error).message} />}
      {dataset === "sales" && sales.data && (
        <Card className="p-4">
          <DataTable columns={saleColumns} rows={sales.data.items} />
          <Pagination page={page} setPage={setPage} total={sales.data.total} pageSize={pageSize} />
        </Card>
      )}
      {dataset === "rentals" && rentals.data && (
        <Card className="p-4">
          <DataTable columns={rentalColumns} rows={rentals.data.items} />
          <Pagination page={page} setPage={setPage} total={rentals.data.total} pageSize={pageSize} />
        </Card>
      )}
    </div>
  );
}

function Pagination({ page, setPage, total, pageSize }: { page: number; setPage: (fn: (p: number) => number) => void; total: number; pageSize: number }) {
  return (
    <div className="flex items-center justify-between mt-3 text-xs text-[var(--text-muted)]">
      <span>{total.toLocaleString()} rows</span>
      <div className="flex gap-2">
        <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-30">Prev</button>
        <span>Page {page}</span>
        <button disabled={page * pageSize >= total} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-30">Next</button>
      </div>
    </div>
  );
}
