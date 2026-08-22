import { useQuery } from "@tanstack/react-query";
import { api, type AreaGrowthItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, ErrorState, KpiCard, LoadingSkeleton, SectionHeader, SignalBadge } from "../components/ui";
import { ProjectSearchBar } from "../components/ProjectSearchBar";
import { formatAed, formatNumber, formatPct } from "../lib/format";
import { Link } from "react-router-dom";

const MOMENTUM_ARROW: Record<string, string> = { accelerating: "▲", slowing: "▼", stable: "→", insufficient_data: "" };
const MOMENTUM_TONE: Record<string, "good" | "bad" | "neutral"> = { accelerating: "good", slowing: "bad", stable: "neutral", insufficient_data: "neutral" };

function AreaGrowthList({ items }: { items: AreaGrowthItem[] }) {
  if (items.length === 0) return <div className="text-xs text-[var(--text-muted)] py-2">No areas meet the sample-size threshold this period.</div>;
  return (
    <ul className="space-y-1.5">
      {items.map((a) => (
        <li key={a.community_key} className="flex items-center justify-between text-sm">
          <Link to={`/communities/${encodeURIComponent(a.community_key)}`} className="text-[var(--accent)]">{a.community_name}</Link>
          <span className={`text-xs ${MOMENTUM_TONE[a.momentum] === "good" ? "text-[var(--good)]" : MOMENTUM_TONE[a.momentum] === "bad" ? "text-[var(--bad)]" : "text-[var(--text-muted)]"}`}>
            {MOMENTUM_ARROW[a.momentum]} {formatPct(a.change_pct, { withSign: true })}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Overview() {
  const { period } = useFilters();
  const { data, isLoading, error } = useQuery({ queryKey: ["overview", period], queryFn: () => api.overview(period) });
  const pulse = useQuery({ queryKey: ["pulse", period], queryFn: () => api.pulse(period, 5) });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold">Dubai Residential Market — Last {data.period}</h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">
          {data.current_range[0]} to {data.current_range[1]} · data covers {data.data_range[0]} to {data.data_range[1]}
        </p>
      </div>

      <ProjectSearchBar />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total Sales" value={formatNumber(data.sales.count)} changePct={data.sales.change_pct} confidence={data.sales.confidence} />
        <KpiCard label="Sales Value" value={data.sales.value_formatted} changePct={data.sales.value_change_pct} />
        <KpiCard label="Median Sale Price" value={formatAed(data.sales.median_price)} sub={`avg ${data.sales.avg_price_formatted}`} />
        <KpiCard label="Median PSF" value={data.sales.median_psf ? `AED ${data.sales.median_psf.toFixed(0)}` : "N/A"} />
        <KpiCard label="Rental Contracts" value={formatNumber(data.rentals.count)} changePct={data.rentals.change_pct} confidence={data.rentals.confidence} />
        <KpiCard label="Median Annual Rent" value={formatAed(data.rentals.median_rent)} sub={`avg ${formatAed(data.rentals.avg_rent)}`} />
        <KpiCard label="Estimated Gross Yield" value={data.estimated_gross_yield_pct !== null ? formatPct(data.estimated_gross_yield_pct) : "N/A"} />
        <KpiCard label="Active Projects" value={formatNumber(data.supply.active_projects)} sub={`${data.supply.under_construction} under construction`} />
      </div>

      <div>
        <SectionHeader title="Snapshot" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card className="p-4">
            <div className="text-xs text-[var(--text-muted)] mb-1">Best-selling unit type</div>
            <div className="text-lg font-medium">{data.best_selling_unit_type?.bedroom ?? "N/A"}</div>
            {data.best_selling_unit_type && <div className="text-xs text-[var(--text-muted)]">{formatNumber(data.best_selling_unit_type.count)} sales this period</div>}
          </Card>
          <Card className="p-4">
            <div className="text-xs text-[var(--text-muted)] mb-1">Highest rental activity</div>
            <div className="text-lg font-medium">{data.highest_rental_activity_area?.community ?? "N/A"}</div>
            {data.highest_rental_activity_area && <div className="text-xs text-[var(--text-muted)]">{formatNumber(data.highest_rental_activity_area.count)} contracts</div>}
          </Card>
          <Card className="p-4">
            <div className="text-xs text-[var(--text-muted)] mb-1">Highest transaction growth</div>
            <div className="text-lg font-medium">{data.highest_transaction_growth_area?.community ?? "N/A"}</div>
            {data.highest_transaction_growth_area && (
              <div className="text-xs text-[var(--good)]">
                {formatPct(data.highest_transaction_growth_area.change_pct, { withSign: true })} vs previous period
              </div>
            )}
          </Card>
          <Card className="p-4">
            <div className="text-xs text-[var(--text-muted)] mb-1">Largest incoming supply</div>
            <div className="text-lg font-medium">{data.largest_incoming_supply?.area ?? "No supply data available"}</div>
            {data.largest_incoming_supply && <div className="text-xs text-[var(--text-muted)]">{formatNumber(data.largest_incoming_supply.units)} units</div>}
          </Card>
        </div>
      </div>

      <div>
        <SectionHeader title="Market Pulse" />
        {pulse.isLoading && <LoadingSkeleton rows={4} />}
        {pulse.error && <ErrorState message={(pulse.error as Error).message} />}
        {pulse.data && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <Card className="p-4">
              <div className="text-xs text-[var(--text-muted)] mb-2">Fastest Growing Areas</div>
              <AreaGrowthList items={pulse.data.fastest_growing_areas} />
            </Card>
            <Card className="p-4">
              <div className="text-xs text-[var(--text-muted)] mb-2">Cooling Areas</div>
              <AreaGrowthList items={pulse.data.cooling_areas} />
            </Card>
            <Card className="p-4">
              <div className="text-xs text-[var(--text-muted)] mb-2">Rental Hotspots</div>
              <AreaGrowthList items={pulse.data.rental_hotspots} />
            </Card>
            <Card className="p-4">
              <div className="text-xs text-[var(--text-muted)] mb-2">Hot Projects</div>
              {pulse.data.hot_projects.length === 0 ? (
                <div className="text-xs text-[var(--text-muted)] py-2">No projects meet the momentum threshold this period.</div>
              ) : (
                <ul className="space-y-1.5">
                  {pulse.data.hot_projects.map((p) => (
                    <li key={p.project_name} className="flex items-center justify-between text-sm">
                      <span className="truncate pr-2">{p.project_name}</span>
                      <SignalBadge tone="good">{p.ratio}x</SignalBadge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card className="p-4">
              <div className="text-xs text-[var(--text-muted)] mb-2">Developer Momentum</div>
              {pulse.data.developer_momentum.length === 0 ? (
                <div className="text-xs text-[var(--text-muted)] py-2">No developers meet the sample-size threshold this period.</div>
              ) : (
                <ul className="space-y-1.5">
                  {pulse.data.developer_momentum.map((d) => (
                    <li key={d.developer_name} className="flex items-center justify-between text-sm">
                      <span className="truncate pr-2">{d.developer_name}</span>
                      <span className="text-xs text-[var(--good)]">{formatPct(d.change_pct, { withSign: true })}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        )}
      </div>

      <div className="text-xs text-[var(--text-muted)]">
        Explore further: <Link to="/sales" className="text-[var(--accent)]">Sales Intelligence</Link> ·{" "}
        <Link to="/rentals" className="text-[var(--accent)]">Rental Intelligence</Link> ·{" "}
        <Link to="/communities" className="text-[var(--accent)]">Communities</Link> ·{" "}
        <Link to="/compare" className="text-[var(--accent)]">Compare</Link> ·{" "}
        <Link to="/signals" className="text-[var(--accent)]">Market Signals</Link> ·{" "}
        <Link to="/decision-engine" className="text-[var(--accent)]">Decision Engine</Link>
      </div>
    </div>
  );
}
