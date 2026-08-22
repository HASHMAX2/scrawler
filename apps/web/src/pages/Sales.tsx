import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { ChartCard } from "../components/ChartCard";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ErrorState, LoadingSkeleton, Select } from "../components/ui";
import { formatAed, formatPct, formatPsf } from "../lib/format";

const BY_OPTIONS = [
  { value: "community", label: "Community" },
  { value: "project", label: "Project" },
  { value: "developer", label: "Developer" },
  { value: "property_type", label: "Property Type" },
  { value: "bedroom", label: "Bedroom" },
  { value: "offplan", label: "Off-Plan / Ready" },
];

interface BreakdownItem { label: string; count: number; value?: number; median_price?: number; median_psf?: number; share_pct: number | null }

export function Sales() {
  const { period } = useFilters();
  const [by, setBy] = useState("community");

  const trend = useQuery({ queryKey: ["sales-trend", period], queryFn: () => api.salesTrend(period, "week") });
  const breakdown = useQuery({ queryKey: ["sales-breakdown", by, period], queryFn: () => api.salesBreakdown(by, period, undefined, 20) });

  if (trend.error) return <ErrorState message={(trend.error as Error).message} />;
  if (breakdown.error) return <ErrorState message={(breakdown.error as Error).message} />;
  if (!trend.data || !breakdown.data) return <LoadingSkeleton rows={6} />;

  const trendOption = {
    xAxis: { type: "category", data: trend.data!.points.map((p) => p.date.slice(0, 10)), axisLine: { lineStyle: { color: "#382c22" } } },
    yAxis: [
      { type: "value", name: "Transactions", position: "left", axisLine: { lineStyle: { color: "#382c22" } }, splitLine: { lineStyle: { color: "#241c16" } } },
      { type: "value", name: "Median PSF", position: "right", axisLine: { lineStyle: { color: "#382c22" } }, splitLine: { show: false } },
    ],
    series: [
      { name: "Transactions", type: "bar", data: trend.data!.points.map((p) => p.count) },
      { name: "Median PSF", type: "line", yAxisIndex: 1, data: trend.data!.points.map((p) => p.median_psf ?? null), smooth: true },
    ],
  };

  const columns: Column<BreakdownItem>[] = [
    { key: "label", header: by === "offplan" ? "Type" : BY_OPTIONS.find((o) => o.value === by)?.label ?? "Label", render: (r) => r.label },
    { key: "count", header: "Transactions", render: (r) => r.count.toLocaleString(), align: "right" },
    { key: "value", header: "Sales Value", render: (r) => formatAed(r.value), align: "right" },
    { key: "median_price", header: "Median Price", render: (r) => formatAed(r.median_price), align: "right" },
    { key: "median_psf", header: "Median PSF", render: (r) => formatPsf(r.median_psf), align: "right" },
    { key: "share", header: "Market Share", render: (r) => formatPct(r.share_pct), align: "right" },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Sales Intelligence</h1>
      <ChartCard title="Transaction Volume & PSF Trend (weekly)" option={trendOption} height={320} />
      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide">Breakdown</h2>
          <Select value={by} onChange={setBy} options={BY_OPTIONS} />
        </div>
        <DataTable columns={columns} rows={breakdown.data!.items} />
      </Card>
    </div>
  );
}
