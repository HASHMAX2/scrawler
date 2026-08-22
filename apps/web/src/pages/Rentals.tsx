import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { ChartCard } from "../components/ChartCard";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ErrorState, LoadingSkeleton, Select } from "../components/ui";
import { formatAed, formatPct } from "../lib/format";

const BY_OPTIONS = [
  { value: "community", label: "Community" },
  { value: "project", label: "Project" },
  { value: "property_type", label: "Property Type" },
  { value: "bedroom", label: "Bedroom" },
  { value: "contract_type", label: "New / Renewal" },
];

interface BreakdownItem { label: string; count: number; median_rent?: number; median_rent_psf?: number; share_pct: number | null }

export function Rentals() {
  const { period } = useFilters();
  const [by, setBy] = useState("community");
  const [matrixMetric, setMatrixMetric] = useState("absolute");

  const trend = useQuery({ queryKey: ["rentals-trend", period], queryFn: () => api.rentalsTrend(period, "week") });
  const breakdown = useQuery({ queryKey: ["rentals-breakdown", by, period], queryFn: () => api.rentalsBreakdown(by, period, undefined, 20) });
  const matrix = useQuery({ queryKey: ["demand-matrix", period, matrixMetric], queryFn: () => api.demandMatrix(period, matrixMetric, 12) });

  if (trend.error) return <ErrorState message={(trend.error as Error).message} />;
  if (!trend.data) return <LoadingSkeleton rows={6} />;

  const trendOption = {
    xAxis: { type: "category", data: trend.data!.points.map((p) => p.date.slice(0, 10)), axisLine: { lineStyle: { color: "#382c22" } } },
    yAxis: { type: "value", axisLine: { lineStyle: { color: "#382c22" } }, splitLine: { lineStyle: { color: "#241c16" } } },
    legend: {},
    series: [
      { name: "New", type: "bar", stack: "c", data: trend.data!.points.map((p) => p.new_contracts ?? 0) },
      { name: "Renewals", type: "bar", stack: "c", data: trend.data!.points.map((p) => p.renewals ?? 0) },
    ],
  };

  const columns: Column<BreakdownItem>[] = [
    { key: "label", header: BY_OPTIONS.find((o) => o.value === by)?.label ?? "Label", render: (r) => r.label },
    { key: "count", header: "Contracts", render: (r) => r.count.toLocaleString(), align: "right" },
    { key: "median_rent", header: "Median Rent", render: (r) => formatAed(r.median_rent), align: "right" },
    { key: "median_rent_psf", header: "Median AED/sqft", render: (r) => (r.median_rent_psf ? r.median_rent_psf.toFixed(0) : "N/A"), align: "right" },
    { key: "share", header: "Share of Activity", render: (r) => formatPct(r.share_pct), align: "right" },
  ];

  const heatColor = (v: number, max: number) => {
    const t = max > 0 ? v / max : 0;
    const alpha = 0.08 + t * 0.55;
    return `rgba(201, 138, 75, ${alpha})`;
  };
  const bedroomsForMatrix = matrix.data?.bedrooms.filter((b) => b !== "Other") ?? [];
  const rowMax = (values: Record<string, number>) => Math.max(1, ...bedroomsForMatrix.map((b) => values[b] ?? 0));

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Rental Intelligence</h1>
      <ChartCard title="New vs Renewal Contracts (weekly)" option={trendOption} height={300} />

      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide">Rental Demand Matrix — Community × Bedroom</h2>
          <Select value={matrixMetric} onChange={setMatrixMetric} options={[{ value: "absolute", label: "Absolute" }, { value: "share", label: "Share of Community" }]} />
        </div>
        {matrix.data && (
          <div className="overflow-x-auto">
            <table className="text-xs w-full">
              <thead>
                <tr>
                  <th className="text-left py-1 px-2 text-[var(--text-muted)]">Community</th>
                  {bedroomsForMatrix.map((b) => (
                    <th key={b} className="text-right py-1 px-2 text-[var(--text-muted)]">{b}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.data.matrix.map((row) => {
                  const max = rowMax(row.values);
                  return (
                    <tr key={row.community_key}>
                      <td className="py-1 px-2 whitespace-nowrap">{row.community_name}</td>
                      {bedroomsForMatrix.map((b) => (
                        <td key={b} className="py-1 px-2 text-right" style={{ background: heatColor(row.values[b] ?? 0, max) }}>
                          {matrixMetric === "share" ? `${(row.values[b] ?? 0).toFixed(0)}%` : row.values[b] ?? 0}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[10px] text-[var(--text-muted)] mt-2">
          Note: apartment bedroom counts are largely absent from Ejari open data — most unit rentals fall in "Unknown". Villa rows are reliable.
        </p>
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide">Breakdown</h2>
          <Select value={by} onChange={setBy} options={BY_OPTIONS} />
        </div>
        {breakdown.data && <DataTable columns={columns} rows={breakdown.data.items} />}
      </Card>
    </div>
  );
}
