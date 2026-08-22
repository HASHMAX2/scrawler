import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type MasterProjectDetail, type RentalRow, type SaleRow, type ScrapedEnrichment } from "../lib/api";
import { ChartCard } from "../components/ChartCard";
import { DataTable, type Column } from "../components/DataTable";
import { Card, ConfidenceBadge, EmptyState, ErrorState, KpiCard, LoadingSkeleton, SectionHeader, Select, SignalBadge } from "../components/ui";
import { formatAed, formatNumber, formatPct, formatPsf } from "../lib/format";

const PERIOD_OPTIONS = [
  { value: "30d", label: "30 Days" },
  { value: "90d", label: "90 Days" },
  { value: "6m", label: "6 Months" },
  { value: "1y", label: "1 Year" },
  { value: "all", label: "All Data" },
];

const UNIT_TYPE_OPTIONS = [
  { value: "", label: "All Unit Types" },
  { value: "Studio", label: "Studio" },
  { value: "1BR", label: "1BR" },
  { value: "2BR", label: "2BR" },
  { value: "3BR", label: "3BR" },
  { value: "4BR", label: "4BR" },
  { value: "5BR+", label: "5BR+" },
  { value: "Other", label: "Other" },
  { value: "Unknown", label: "Unknown" },
];

const TRANSACTION_TYPE_OPTIONS = [
  { value: "", label: "All Transactions" },
  { value: "offplan", label: "Off-Plan" },
  { value: "ready", label: "Ready" },
];

const MOMENTUM_TONE: Record<string, "good" | "bad" | "neutral"> = { accelerating: "good", slowing: "bad", stable: "neutral", insufficient_data: "neutral" };

type ExplorerFilters = { master_slug?: string; building_slug?: string };

export function ProjectIntelligence() {
  const { slug, buildingSlug } = useParams<{ slug: string; buildingSlug?: string }>();
  const navigate = useNavigate();
  const [period, setPeriod] = useState("90d");
  const [unitType, setUnitType] = useState("");
  const [transactionType, setTransactionType] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["master-project", slug, period, buildingSlug, unitType, transactionType],
    queryFn: () => api.masterProjectDetail(slug!, period, buildingSlug, unitType || undefined, transactionType || undefined),
    enabled: !!slug,
  });

  const selectBuilding = (bSlug: string | null) => {
    navigate(bSlug ? `/projects/${slug}/buildings/${bSlug}` : `/projects/${slug}`);
  };

  if (isLoading) return <LoadingSkeleton rows={8} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  const explorerFilters: ExplorerFilters = buildingSlug ? { building_slug: buildingSlug } : { master_slug: slug };

  return (
    <div className="space-y-6">
      <ProjectHeader data={data} />

      <BuildingSelector data={data} activeBuildingSlug={buildingSlug ?? null} onSelect={selectBuilding} />

      {data.scraped_enrichment && <ScrapedProfileSection enrichment={data.scraped_enrichment} buildingCount={data.building_count} />}

      <Card className="p-3 flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {PERIOD_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setPeriod(o.value)}
              className={`text-xs px-3 py-1.5 rounded ${period === o.value ? "bg-[var(--accent-soft)] text-[var(--accent)]" : "text-[var(--text-muted)] hover:bg-[var(--hover-overlay)]"}`}
            >
              {o.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          <Select value={unitType} onChange={setUnitType} options={UNIT_TYPE_OPTIONS} />
          <Select value={transactionType} onChange={setTransactionType} options={TRANSACTION_TYPE_OPTIONS} />
        </div>
      </Card>

      <KpiRow data={data} />

      <MarketActivity data={data} />

      <UnitTypePerformance items={data.unit_type_performance} />

      <BuildingPerformance data={data} activeBuildingSlug={buildingSlug ?? null} onSelect={selectBuilding} />

      <SalesVsRentals data={data} />

      <RecentTransactions filters={explorerFilters} />
      <RecentRentals filters={explorerFilters} />

      <DataQualityFooter data={data} />
    </div>
  );
}

function ProjectHeader({ data }: { data: MasterProjectDetail }) {
  const heroUrl = data.scraped_enrichment?.hero_image_url;
  return (
    <div>
      <Link to="/" className="text-xs text-[var(--accent)]">&larr; Overview</Link>
      {heroUrl && (
        <div className="mt-2 rounded-lg overflow-hidden border border-[var(--border)]" style={{ height: 180 }}>
          <img src={heroUrl} alt={data.name} className="w-full h-full object-cover" loading="lazy" />
        </div>
      )}
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        <h1 className="text-xl font-semibold uppercase tracking-wide">{data.name}</h1>
        {data.needs_review && <SignalBadge tone="warn">grouping needs review</SignalBadge>}
      </div>
      <p className="text-xs text-[var(--text-muted)] mt-1">
        {data.developer_name ? `Developer: ${data.developer_name}` : "Developer: No data available"}
        {" · "}
        {data.area_name ? `Area: ${data.area_name}` : "Area: No data available"}
        {" · "}
        {data.building_count > 1 ? `Master Development · ${data.building_count} buildings` : "Single Building Project"}
      </p>
    </div>
  );
}

const STATUS_TONE: Record<string, "good" | "bad" | "warn" | "neutral"> = {
  completed: "good", under_construction: "warn", planned: "neutral", announced: "neutral",
  on_hold: "bad", delayed: "bad", cancelled: "bad", other: "neutral",
};

function ScrapedProfileSection({ enrichment: e, buildingCount }: { enrichment: ScrapedEnrichment; buildingCount: number }) {
  return (
    <div className="space-y-4">
      <SectionHeader
        title="Project Profile"
        action={
          buildingCount > 1 ? (
            <span className="text-[10px] text-[var(--text-muted)]">
              Scraped profile shown for {e.source_building_name ?? "one building"} in this family
            </span>
          ) : undefined
        }
      />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="p-4 space-y-2 md:col-span-2">
          <div className="flex items-center gap-2 flex-wrap">
            {e.status && <SignalBadge tone={STATUS_TONE[e.status] ?? "neutral"}>{e.status.replace("_", " ")}</SignalBadge>}
            {e.building_type && <span className="text-xs text-[var(--text-muted)]">{e.building_type}</span>}
            {e.storeys && <span className="text-xs text-[var(--text-muted)]">· {e.storeys}</span>}
          </div>
          {e.overview_text && <p className="text-sm text-[var(--text)]">{e.overview_text}</p>}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs pt-2">
            {e.total_units !== null && (
              <div><span className="text-[var(--text-muted)]">Total Units:</span> {e.total_units.toLocaleString()}</div>
            )}
            {(e.project_value_aed !== null || e.project_value_usd !== null) && (
              <div>
                <span className="text-[var(--text-muted)]">Project Value:</span>{" "}
                {e.project_value_aed !== null ? formatAed(e.project_value_aed) : null}
                {e.project_value_usd !== null ? ` (USD ${(e.project_value_usd / 1_000_000).toFixed(1)}M)` : null}
              </div>
            )}
            {e.plot_reference && <div><span className="text-[var(--text-muted)]">Plot:</span> {e.plot_reference}</div>}
            {e.official_website && (
              <div>
                <span className="text-[var(--text-muted)]">Website:</span>{" "}
                <a href={e.official_website} target="_blank" rel="noreferrer" className="text-[var(--accent)]">Official site &#8599;</a>
              </div>
            )}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-2">Companies</div>
          {e.companies.length === 0 ? (
            <div className="text-xs text-[var(--text-muted)]">No company data available</div>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {e.companies.map((c, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span className="text-[var(--text-muted)]">{c.role}</span>
                  {c.url ? (
                    <a href={c.url} target="_blank" rel="noreferrer" className="text-[var(--accent)] text-right">{c.name}</a>
                  ) : (
                    <span className="text-right">{c.name}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {e.milestones.length > 0 && <ConstructionTimeline milestones={e.milestones} />}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {e.updates.length > 0 && (
          <Card className="p-4">
            <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-2">Construction Updates</div>
            <ul className="space-y-2 text-xs max-h-64 overflow-y-auto">
              {e.updates.map((u, i) => (
                <li key={i} className="border-b border-[var(--border)]/40 pb-2">
                  <div className="text-[var(--text-muted)]">{u.date_raw ?? u.date_parsed}</div>
                  <div>{u.description}</div>
                </li>
              ))}
            </ul>
          </Card>
        )}
        {e.documents.length > 0 && (
          <Card className="p-4">
            <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-2">Photos</div>
            <div className="space-y-3">
              {e.documents.map((d) => (
                <div key={d.doc_type}>
                  <div className="text-xs text-[var(--text-muted)] mb-1">
                    {d.doc_type.replace("_", " ")} ({d.total_photos})
                  </div>
                  <div className="flex gap-1.5">
                    {d.cover_photo_urls.map((url, i) => (
                      <a key={i} href={url} target="_blank" rel="noreferrer" className="block w-16 h-16 rounded overflow-hidden border border-[var(--border)]">
                        <img src={url} alt="" className="w-full h-full object-cover" loading="lazy" />
                      </a>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function ConstructionTimeline({ milestones }: { milestones: ScrapedEnrichment["milestones"] }) {
  return (
    <Card className="p-4">
      <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-3">Construction Timeline</div>
      <div className="flex items-stretch gap-0 overflow-x-auto">
        {milestones.map((m, i) => (
          <div key={i} className="flex items-center shrink-0">
            <div className="flex flex-col items-center gap-1 px-3">
              <div className="w-2.5 h-2.5 rounded-full bg-[var(--accent)]" />
              <div className="text-xs font-medium text-center whitespace-nowrap">{m.label}</div>
              <div className="text-[10px] text-[var(--text-muted)]">{m.date_raw ?? m.date_parsed ?? "N/A"}</div>
            </div>
            {i < milestones.length - 1 && <div className="h-px w-8 bg-[var(--border)]" />}
          </div>
        ))}
      </div>
    </Card>
  );
}

function BuildingSelector({ data, activeBuildingSlug, onSelect }: { data: MasterProjectDetail; activeBuildingSlug: string | null; onSelect: (s: string | null) => void }) {
  if (data.building_count <= 1) return null;
  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1">
      <button
        onClick={() => onSelect(null)}
        className={`shrink-0 text-xs px-3 py-1.5 rounded-full border ${!activeBuildingSlug ? "bg-[var(--accent-soft)] text-[var(--accent)] border-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--hover-overlay)]"}`}
      >
        All Buildings
      </button>
      {data.buildings.map((b) => (
        <button
          key={b.slug}
          onClick={() => onSelect(b.slug)}
          className={`shrink-0 text-xs px-3 py-1.5 rounded-full border ${activeBuildingSlug === b.slug ? "bg-[var(--accent-soft)] text-[var(--accent)] border-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--hover-overlay)]"}`}
        >
          {b.building_label ?? b.name}
        </button>
      ))}
    </div>
  );
}

function KpiRow({ data }: { data: MasterProjectDetail }) {
  const { sales, rentals, market } = data.kpis;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <KpiCard label="Sales" value={formatNumber(sales.count)} changePct={sales.count_change_pct} confidence={sales.confidence} sub={`30d: ${sales.count_30d} · 90d: ${sales.count_90d}`} />
      <KpiCard label="Sales Value" value={formatAed(sales.value)} />
      <KpiCard label="Avg / Median Price" value={formatAed(sales.avg_price)} sub={`median ${formatAed(sales.median_price)}`} />
      <KpiCard label="Avg / Median PSF" value={sales.avg_psf ? `AED ${sales.avg_psf.toFixed(0)}` : "N/A"} sub={sales.median_psf ? `median AED ${sales.median_psf.toFixed(0)}` : undefined} />
      <KpiCard label="Rentals" value={formatNumber(rentals.count)} changePct={rentals.count_change_pct} confidence={rentals.confidence} sub={rentals.new_count !== null ? `new: ${rentals.new_count} · renewal: ${rentals.renewal_count}` : undefined} />
      <KpiCard label="Avg / Median Rent" value={formatAed(rentals.avg_rent)} sub={rentals.median_rent ? `median ${formatAed(rentals.median_rent)}` : undefined} />
      <KpiCard label="Estimated Gross Yield" value={market.estimated_gross_yield_pct !== null ? formatPct(market.estimated_gross_yield_pct) : "N/A"} />
      <KpiCard label="Sales Velocity" value={`${market.sales_velocity_per_day.toFixed(2)}/day`} sub={`rentals ${market.rental_velocity_per_day.toFixed(2)}/day`} />
    </div>
  );
}

function MarketActivity({ data }: { data: MasterProjectDetail }) {
  const dates = data.trends.sales.map((p) => p.date.slice(0, 10));
  const axisStyle = { axisLine: { lineStyle: { color: "#382c22" } }, splitLine: { lineStyle: { color: "#241c16" } } };

  const volumeOption = {
    xAxis: { type: "category", data: dates, axisLine: axisStyle.axisLine },
    yAxis: { type: "value", ...axisStyle },
    series: [{ type: "bar", data: data.trends.sales.map((p) => p.count) }],
  };
  const valueOption = {
    xAxis: { type: "category", data: dates, axisLine: axisStyle.axisLine },
    yAxis: { type: "value", ...axisStyle },
    series: [{ type: "bar", data: data.trends.sales.map((p) => p.value) }],
  };
  const psfOption = {
    xAxis: { type: "category", data: dates, axisLine: axisStyle.axisLine },
    yAxis: { type: "value", ...axisStyle },
    series: [{ type: "line", smooth: true, data: data.trends.sales.map((p) => p.avg_psf) }],
  };
  const rentalDates = data.trends.rentals.map((p) => p.date.slice(0, 10));
  const rentalVolumeOption = {
    xAxis: { type: "category", data: rentalDates, axisLine: axisStyle.axisLine },
    yAxis: { type: "value", ...axisStyle },
    series: [{ type: "bar", data: data.trends.rentals.map((p) => p.count) }],
  };

  return (
    <div>
      <SectionHeader title="Market Activity" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {dates.length === 0 ? (
          <EmptyState title="No sales activity in this period" />
        ) : (
          <>
            <ChartCard title="Transaction Volume (weekly)" option={volumeOption} height={240} />
            <ChartCard title="Sales Value (weekly)" option={valueOption} height={240} />
            <ChartCard title="Average PSF Trend" option={psfOption} height={240} />
          </>
        )}
        {rentalDates.length === 0 ? (
          <EmptyState title="No rental activity in this period" />
        ) : (
          <ChartCard title="Rental Volume (weekly)" option={rentalVolumeOption} height={240} />
        )}
      </div>
    </div>
  );
}

function UnitTypePerformance({ items }: { items: MasterProjectDetail["unit_type_performance"] }) {
  const columns: Column<MasterProjectDetail["unit_type_performance"][number]>[] = [
    { key: "bedroom", header: "Unit Type", render: (r) => <span className="font-medium">{r.bedroom}</span> },
    { key: "sales", header: "Sales", render: (r) => `${r.sales_count} (${formatPct(r.sales_share_pct)})`, align: "right" },
    { key: "avg_price", header: "Avg Price", render: (r) => formatAed(r.avg_price), align: "right" },
    { key: "avg_psf", header: "Avg PSF", render: (r) => formatPsf(r.avg_psf), align: "right" },
    { key: "rentals", header: "Rentals", render: (r) => `${r.rental_count} (${formatPct(r.rental_share_pct)})`, align: "right" },
    { key: "avg_rent", header: "Avg Rent", render: (r) => formatAed(r.avg_rent), align: "right" },
    { key: "yield", header: "Est. Yield", render: (r) => (r.estimated_gross_yield_pct !== null ? formatPct(r.estimated_gross_yield_pct) : "N/A"), align: "right" },
  ];
  return (
    <div>
      <SectionHeader title="Unit Type Performance" />
      <Card className="p-4">
        {items.length === 0 ? <EmptyState title="No unit-type data available for this scope" /> : <DataTable columns={columns} rows={items} />}
      </Card>
    </div>
  );
}

function BuildingPerformance({ data, activeBuildingSlug, onSelect }: { data: MasterProjectDetail; activeBuildingSlug: string | null; onSelect: (s: string | null) => void }) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<"sales_count" | "sales_value" | "avg_price" | "avg_psf" | "rental_count" | "avg_rent">("sales_count");

  if (data.building_count <= 1) return null;

  const filtered = data.building_performance.filter((b) => b.name.toLowerCase().includes(search.toLowerCase()));
  const sorted = [...filtered].sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0) || 0);

  const columns: Column<MasterProjectDetail["building_performance"][number]>[] = [
    { key: "name", header: "Building", render: (r) => (
      <span className="flex items-center gap-1.5">
        {r.name}
        {r.slug === activeBuildingSlug && <SignalBadge tone="good">selected</SignalBadge>}
        {!r.has_scraped_profile && <SignalBadge tone="neutral">unmatched</SignalBadge>}
      </span>
    ) },
    { key: "sales_count", header: "Sales", render: (r) => r.sales_count.toLocaleString(), align: "right" },
    { key: "sales_value", header: "Sales Value", render: (r) => formatAed(r.sales_value), align: "right" },
    { key: "avg_price", header: "Avg Price", render: (r) => formatAed(r.avg_price), align: "right" },
    { key: "avg_psf", header: "Avg PSF", render: (r) => formatPsf(r.avg_psf), align: "right" },
    { key: "rental_count", header: "Rentals", render: (r) => r.rental_count.toLocaleString(), align: "right" },
    { key: "avg_rent", header: "Avg Rent", render: (r) => formatAed(r.avg_rent), align: "right" },
    { key: "yield", header: "Yield", render: (r) => (r.estimated_gross_yield_pct !== null ? formatPct(r.estimated_gross_yield_pct) : "N/A"), align: "right" },
    { key: "last_tx", header: "Last Transaction", render: (r) => r.last_transaction_date ?? "N/A" },
  ];

  return (
    <div>
      <SectionHeader
        title="Building Performance"
        action={
          <div className="flex items-center gap-2">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter buildings..."
              className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1 text-xs focus:outline-none focus:border-[var(--accent)]"
            />
            <Select
              value={sortKey}
              onChange={(v) => setSortKey(v as typeof sortKey)}
              options={[
                { value: "sales_count", label: "Sort: Sales" },
                { value: "sales_value", label: "Sort: Sales Value" },
                { value: "avg_price", label: "Sort: Avg Price" },
                { value: "avg_psf", label: "Sort: Avg PSF" },
                { value: "rental_count", label: "Sort: Rentals" },
                { value: "avg_rent", label: "Sort: Avg Rent" },
              ]}
            />
          </div>
        }
      />
      <Card className="p-4">
        <DataTable columns={columns} rows={sorted} onRowClick={(r) => onSelect(r.slug)} />
      </Card>
    </div>
  );
}

function SalesVsRentals({ data }: { data: MasterProjectDetail }) {
  const svr = data.sales_vs_rentals;
  return (
    <div>
      <SectionHeader title="Sales vs Rental Analysis" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Sales Demand</div><div className="text-lg font-medium">{formatNumber(svr.sales_demand_count)}</div></Card>
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Rental Demand</div><div className="text-lg font-medium">{formatNumber(svr.rental_demand_count)}</div></Card>
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Rental-to-Sales Ratio</div><div className="text-lg font-medium">{svr.rental_to_sales_ratio ?? "N/A"}</div></Card>
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Estimated Yield</div><div className="text-lg font-medium">{svr.estimated_gross_yield_pct !== null ? formatPct(svr.estimated_gross_yield_pct) : "N/A"}</div></Card>
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Most Liquid Unit Type</div><div className="text-lg font-medium">{svr.most_liquid_unit_type ?? "No data available"}</div></Card>
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Most Rented Unit Type</div><div className="text-lg font-medium">{svr.most_rented_unit_type ?? "No data available"}</div></Card>
        <Card className="p-4"><div className="text-xs text-[var(--text-muted)]">Highest Transaction Volume</div><div className="text-lg font-medium">{svr.highest_volume_unit_type ?? "No data available"}</div></Card>
      </div>
    </div>
  );
}

function RecentTransactions({ filters }: { filters: ExplorerFilters }) {
  const { data, isLoading } = useQuery({
    queryKey: ["project-recent-sales", filters],
    queryFn: () => api.explorerSales(1, 20, filters as Record<string, string | undefined>),
  });
  const columns: Column<SaleRow>[] = [
    { key: "date", header: "Date", render: (r) => r.instance_date },
    { key: "building", header: "Building", render: (r) => r.project ?? "—" },
    { key: "type", header: "Unit Type", render: (r) => r.property_type },
    { key: "bedroom", header: "Bedrooms", render: (r) => r.bedroom ?? "—" },
    { key: "area", header: "Area (sqm)", render: (r) => r.area_sqm?.toFixed(0) ?? "—", align: "right" },
    { key: "price", header: "Price", render: (r) => formatAed(r.price), align: "right" },
    { key: "psf", header: "PSF", render: (r) => (r.price_per_sqft ? r.price_per_sqft.toFixed(0) : "—"), align: "right" },
    { key: "offplan", header: "Type", render: (r) => (r.is_offplan ? "Off-Plan" : "Ready") },
  ];
  return (
    <div>
      <SectionHeader title="Recent Transactions" />
      <Card className="p-4">
        {isLoading ? <LoadingSkeleton rows={5} /> : data && data.items.length > 0 ? (
          <>
            <DataTable columns={columns} rows={data.items} />
            <p className="text-xs text-[var(--text-muted)] mt-2">Showing latest 20 of {data.total.toLocaleString()} transactions.</p>
          </>
        ) : (
          <EmptyState title="No transactions available" />
        )}
      </Card>
    </div>
  );
}

function RecentRentals({ filters }: { filters: ExplorerFilters }) {
  const { data, isLoading } = useQuery({
    queryKey: ["project-recent-rentals", filters],
    queryFn: () => api.explorerRentals(1, 20, filters as Record<string, string | undefined>),
  });
  const columns: Column<RentalRow>[] = [
    { key: "date", header: "Contract Date", render: (r) => r.registration_date },
    { key: "building", header: "Building", render: (r) => r.project ?? "—" },
    { key: "type", header: "Unit Type", render: (r) => r.property_type },
    { key: "bedroom", header: "Bedrooms", render: (r) => r.bedroom ?? "—" },
    { key: "area", header: "Area (sqm)", render: (r) => r.area_sqm?.toFixed(0) ?? "—", align: "right" },
    { key: "rent", header: "Annual Rent", render: (r) => formatAed(r.annual_rent), align: "right" },
    { key: "psf", header: "Rent PSF", render: (r) => (r.rent_per_sqft ? r.rent_per_sqft.toFixed(0) : "—"), align: "right" },
    { key: "renewal", header: "New/Renewal", render: (r) => (r.is_renewal ? "Renewal" : "New") },
  ];
  return (
    <div>
      <SectionHeader title="Recent Rentals" />
      <Card className="p-4">
        {isLoading ? <LoadingSkeleton rows={5} /> : data && data.items.length > 0 ? (
          <>
            <DataTable columns={columns} rows={data.items} />
            <p className="text-xs text-[var(--text-muted)] mt-2">Showing latest 20 of {data.total.toLocaleString()} rentals.</p>
          </>
        ) : (
          <EmptyState title="No rental data available for this scope" />
        )}
      </Card>
    </div>
  );
}

function DataQualityFooter({ data }: { data: MasterProjectDetail }) {
  const dq = data.data_quality;
  return (
    <div>
      <SectionHeader title="Data Quality / Source Information" />
      <Card className="p-4 text-xs text-[var(--text-muted)] space-y-1">
        <div>
          {dq.total_buildings} building{dq.total_buildings !== 1 ? "s" : ""} in this family ·{" "}
          {dq.matched_scraped_buildings} matched to scraped development records ·{" "}
          grouping: {Object.entries(dq.grouping_method_summary).map(([m, n]) => `${m.replace("_", " ")} (${n})`).join(", ")}
        </div>
        <div>Source: DLD sales/rental transaction records, entity-resolved to this project via deterministic name normalization.</div>
        {data.needs_review && <div className="text-[var(--warn)]">This grouping includes a lower-confidence match (hyphen-split or manual override) — verify on the Data Quality page.</div>}
        <div className="flex items-center gap-2">Confidence: <ConfidenceBadge confidence={data.kpis.sales.confidence} /> sales sample, <ConfidenceBadge confidence={data.kpis.rentals.confidence} /> rental sample</div>
      </Card>
    </div>
  );
}
