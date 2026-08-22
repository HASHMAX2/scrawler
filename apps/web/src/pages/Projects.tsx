import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type ProjectListItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ErrorState, LoadingSkeleton } from "../components/ui";
import { formatAed } from "../lib/format";

export function Projects() {
  const { period } = useFilters();
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({ queryKey: ["projects", search, period], queryFn: () => api.projects(search || undefined, period, 50) });

  const columns: Column<ProjectListItem>[] = [
    { key: "name", header: "Project", render: (r) => r.name },
    { key: "developer", header: "Developer", render: (r) => r.developer_name ?? "Unknown (unmatched to scraper)" },
    { key: "sales_count", header: "Sales", render: (r) => r.sales_count.toLocaleString(), align: "right" },
    { key: "sales_value", header: "Sales Value", render: (r) => formatAed(r.sales_value), align: "right" },
    { key: "rental_count", header: "Rentals", render: (r) => r.rental_count.toLocaleString(), align: "right" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Projects</h1>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search project..."
          className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
        />
      </div>
      {isLoading && <LoadingSkeleton rows={8} />}
      {error && <ErrorState message={(error as Error).message} />}
      {data && (
        <Card className="p-4">
          <DataTable
            columns={columns}
            rows={data.items}
            onRowClick={(r) => navigate(r.building_slug && r.master_slug ? `/projects/${r.master_slug}/buildings/${r.building_slug}` : "/projects")}
          />
        </Card>
      )}
    </div>
  );
}
