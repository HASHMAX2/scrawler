import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type LivabilityPanel as LivabilityPanelData } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, ErrorState, KpiCard, LoadingSkeleton, SectionHeader, SignalBadge } from "../components/ui";
import { formatAed, formatNumber, formatPct, onHeroImageError, upgradeToXlImage } from "../lib/format";

export function CommunityDetail() {
  const { key } = useParams<{ key: string }>();
  const { period } = useFilters();
  const { data, isLoading, error } = useQuery({
    queryKey: ["community-detail", key, period],
    queryFn: () => api.communityDetail(key!, period),
    enabled: !!key,
  });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  const profile = data.area_profile;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/communities" className="text-xs text-[var(--accent)]">&larr; Communities</Link>
        {profile?.hero_image_url && (
          <div className="mt-2 rounded-lg overflow-hidden border border-[var(--border)]" style={{ height: 160 }}>
            <img
              src={upgradeToXlImage(profile.hero_image_url)}
              onError={onHeroImageError(profile.hero_image_url)}
              alt={data.community_name}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          </div>
        )}
        <div className="flex items-center gap-2 mt-2">
          <h1 className="text-lg font-semibold">{data.community_name}</h1>
          {profile?.also_known_as && <span className="text-xs text-[var(--text-muted)]">({profile.also_known_as})</span>}
          {!data.has_scraped_profile && <SignalBadge tone="neutral">No scraped profile — DLD data only</SignalBadge>}
          {data.has_scraped_profile && data.community_key.startsWith("s") && (
            <Link to={`/areas/${data.community_key.slice(1)}`}>
              <SignalBadge tone="good">Browse sub-areas &rarr;</SignalBadge>
            </Link>
          )}
        </div>
        {profile?.description && <p className="text-xs text-[var(--text-muted)] mt-1 max-w-2xl">{profile.description}</p>}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Sales" value={data.sales.count.toLocaleString()} confidence={data.sales.confidence} />
        <KpiCard label="Sales Value" value={formatAed(data.sales.value)} />
        <KpiCard label="Median Price" value={formatAed(data.sales.median_price)} sub={data.sales.median_psf ? `AED ${data.sales.median_psf.toFixed(0)}/sqft` : undefined} />
        <KpiCard label="Est. Gross Yield" value={data.estimated_gross_yield_pct !== null ? formatPct(data.estimated_gross_yield_pct) : "N/A"} />
        <KpiCard label="Rental Contracts" value={data.rentals.count.toLocaleString()} confidence={data.rentals.confidence} />
        <KpiCard label="Median Rent" value={formatAed(data.rentals.median_rent)} />
        <KpiCard label="New Contracts" value={formatNumber(data.rentals.new_contracts)} />
        <KpiCard label="Renewals" value={formatNumber(data.rentals.renewals)} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="p-4">
          <SectionHeader title="Sales by Bedroom" />
          <ul className="space-y-1 text-sm">
            {data.bedroom_demand.sales.map((b) => (
              <li key={b.bedroom} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                <span>{b.bedroom}</span>
                <span className="text-[var(--text-muted)]">{b.count.toLocaleString()} ({formatPct(b.share_pct)})</span>
              </li>
            ))}
            {data.bedroom_demand.sales.length === 0 && <li className="text-[var(--text-muted)]">No sales in this period</li>}
          </ul>
        </Card>
        <Card className="p-4">
          <SectionHeader title="Rentals by Bedroom" />
          <ul className="space-y-1 text-sm">
            {data.bedroom_demand.rentals.map((b) => (
              <li key={b.bedroom} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                <span>{b.bedroom}</span>
                <span className="text-[var(--text-muted)]">{b.count.toLocaleString()} ({formatPct(b.share_pct)}) · {formatAed(b.median_rent)}</span>
              </li>
            ))}
            {data.bedroom_demand.rentals.length === 0 && <li className="text-[var(--text-muted)]">No rentals in this period</li>}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="p-4">
          <SectionHeader title="Top Projects" />
          <ul className="space-y-1 text-sm">
            {data.top_projects.map((p) => (
              <li key={p.name} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                <span>{p.name}</span>
                <span className="text-[var(--text-muted)]">{p.sales_count} sales · {formatAed(p.sales_value)}</span>
              </li>
            ))}
            {data.top_projects.length === 0 && <li className="text-[var(--text-muted)]">No matched projects in this period</li>}
          </ul>
        </Card>
        <Card className="p-4">
          <SectionHeader title="Top Developers" />
          <ul className="space-y-1 text-sm">
            {data.top_developers.map((d) => (
              <li key={d.name} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                <span>{d.name}</span>
                <span className="text-[var(--text-muted)]">{d.project_count} projects</span>
              </li>
            ))}
            {data.top_developers.length === 0 && <li className="text-[var(--text-muted)]">No scraped developer data for this community</li>}
          </ul>
          {data.upcoming_supply_units !== null && (
            <p className="text-xs text-[var(--text-muted)] mt-3">Upcoming supply: {data.upcoming_supply_units.toLocaleString()} units under construction/planned</p>
          )}
        </Card>
      </div>

      {data.livability && <LivabilityPanel livability={data.livability} />}

      <Card className="p-4">
        <SectionHeader title="Oversupply Risk" />
        {data.oversupply_risk.risk === "insufficient_data" ? (
          <p className="text-xs text-[var(--text-muted)]">
            {data.oversupply_risk.incoming_units === null ? "No scraped supply data available for this community." : "Insufficient data to assess risk."}
          </p>
        ) : (
          <div className="flex items-center gap-3">
            <SignalBadge tone={data.oversupply_risk.risk === "very_high" ? "bad" : data.oversupply_risk.risk === "high" ? "warn" : "good"}>
              {data.oversupply_risk.risk.replace("_", " ")}
            </SignalBadge>
            <span className="text-xs text-[var(--text-muted)]">
              {data.oversupply_risk.incoming_units?.toLocaleString()} incoming units vs ~{data.oversupply_risk.trailing_annualized_demand?.toLocaleString()} annualized demand (ratio {data.oversupply_risk.ratio})
            </span>
          </div>
        )}
        <p className="text-[10px] text-[var(--text-muted)] mt-2">{data.oversupply_risk.note ?? "Non-predictive: incoming known units relative to trailing observed demand, not a forecast."}</p>
      </Card>
    </div>
  );
}

function LivabilityPanel({ livability }: { livability: LivabilityPanelData }) {
  if (livability.total_amenities === 0 && livability.total_schools === 0) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card className="p-4">
        <SectionHeader title={`Amenities (${livability.total_amenities})`} />
        <ul className="space-y-1 text-sm">
          {livability.amenity_counts.map((a) => (
            <li key={a.category} className="flex justify-between border-b border-[var(--border)]/40 py-1">
              <span>{a.category}</span>
              <span className="text-[var(--text-muted)]">{a.count.toLocaleString()}</span>
            </li>
          ))}
          {livability.amenity_counts.length === 0 && <li className="text-[var(--text-muted)]">No scraped amenity data for this area</li>}
        </ul>
      </Card>
      <Card className="p-4">
        <SectionHeader
          title={`Schools (${livability.total_schools})`}
          action={
            <span className="text-[10px] text-[var(--text-muted)]">
              {livability.school_curriculum_counts.map((c) => `${c.curriculum.replace(" Schools", "")}: ${c.count}`).join(" · ")}
            </span>
          }
        />
        <ul className="space-y-1.5 text-sm max-h-64 overflow-y-auto">
          {livability.top_schools.map((s) => (
            <li key={s.name} className="border-b border-[var(--border)]/40 py-1">
              <div className="flex justify-between">
                <span>{s.name}</span>
                {s.rating && <span className="text-[var(--text-muted)] text-xs">{s.rating}</span>}
              </div>
              <div className="text-[10px] text-[var(--text-muted)]">
                {s.curriculum}{s.distance_text ? ` · ${s.distance_text}` : ""}{s.fees_text ? ` · ${s.fees_text}` : ""}
              </div>
            </li>
          ))}
          {livability.top_schools.length === 0 && <li className="text-[var(--text-muted)]">No scraped school data for this area</li>}
        </ul>
      </Card>
    </div>
  );
}
