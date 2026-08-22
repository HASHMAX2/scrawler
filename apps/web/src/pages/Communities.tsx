import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type CommunityListItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ErrorState, LoadingSkeleton, SignalBadge } from "../components/ui";
import { formatAed, formatPct, formatPsf } from "../lib/format";

export function Communities() {
  const { period } = useFilters();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const pageSize = 25;

  const { data, isLoading, error } = useQuery({
    queryKey: ["communities", period, page, search],
    queryFn: () => api.communities(period, page, pageSize, "sales_count", search || undefined),
  });

  const columns: Column<CommunityListItem>[] = [
    {
      key: "name", header: "Community",
      render: (r) => (
        <span className="flex items-center gap-2">
          {r.hero_image_url ? (
            <img src={r.hero_image_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" loading="lazy" />
          ) : (
            <span className="w-8 h-8 rounded bg-[var(--surface-2)] shrink-0" />
          )}
          {r.community_name}
          {!r.has_scraped_profile && <SignalBadge tone="neutral">no profile yet</SignalBadge>}
        </span>
      ),
    },
    { key: "sales_count", header: "Sales", render: (r) => r.sales_count.toLocaleString(), align: "right" },
    { key: "sales_value", header: "Sales Value", render: (r) => formatAed(r.sales_value), align: "right" },
    { key: "median_price", header: "Median Price", render: (r) => formatAed(r.median_price), align: "right" },
    { key: "median_psf", header: "PSF", render: (r) => formatPsf(r.median_psf), align: "right" },
    { key: "rental_count", header: "Rentals", render: (r) => r.rental_count.toLocaleString(), align: "right" },
    { key: "median_rent", header: "Median Rent", render: (r) => formatAed(r.median_rent), align: "right" },
    { key: "yield", header: "Est. Yield", render: (r) => (r.estimated_gross_yield_pct !== null ? formatPct(r.estimated_gross_yield_pct) : "N/A"), align: "right" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Communities</h1>
        <input
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          placeholder="Search community..."
          className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
        />
      </div>
      {isLoading && <LoadingSkeleton rows={8} />}
      {error && <ErrorState message={(error as Error).message} />}
      {data && (
        <Card className="p-4">
          <DataTable columns={columns} rows={data.items} onRowClick={(r) => navigate(`/communities/${encodeURIComponent(r.community_key)}`)} />
          <div className="flex items-center justify-between mt-3 text-xs text-[var(--text-muted)]">
            <span>{data.total.toLocaleString()} communities</span>
            <div className="flex gap-2">
              <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-30">Prev</button>
              <span>Page {page}</span>
              <button disabled={page * pageSize >= data.total} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-30">Next</button>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
