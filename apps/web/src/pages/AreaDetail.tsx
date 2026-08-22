import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type AreaChildItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, KpiCard, LoadingSkeleton, SectionHeader, SignalBadge } from "../components/ui";
import { formatAed, formatPct, onHeroImageError, upgradeToXlImage } from "../lib/format";

export function AreaDetail() {
  const { areaId } = useParams<{ areaId: string }>();
  const navigate = useNavigate();
  const { period } = useFilters();
  const { data, isLoading, error } = useQuery({
    queryKey: ["area-detail", areaId, period],
    queryFn: () => api.areaDetail(areaId!, period),
    enabled: !!areaId,
  });

  if (isLoading) return <LoadingSkeleton rows={8} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  const hero = data.profile?.hero_image_url;
  const hasOwnActivity = data.own_stats.sales_count > 0 || data.own_stats.rental_count > 0;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs text-[var(--accent)] flex items-center gap-1 flex-wrap">
          <Link to="/areas">Areas</Link>
          {data.breadcrumb.map((b) => (
            <span key={b.area_id} className="flex items-center gap-1">
              <span className="text-[var(--text-muted)]">/</span>
              <Link to={`/areas/${b.area_id}`}>{b.name}</Link>
            </span>
          ))}
          <span className="text-[var(--text-muted)]">/</span>
          <span className="text-[var(--text)]">{data.name}</span>
        </div>

        {hero && (
          <div className="mt-2 rounded-lg overflow-hidden border border-[var(--border)]" style={{ height: 160 }}>
            <img src={upgradeToXlImage(hero)} onError={onHeroImageError(hero)} alt={data.name} className="w-full h-full object-cover" loading="lazy" />
          </div>
        )}

        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <h1 className="text-xl font-semibold">{data.name}</h1>
          {data.profile?.also_known_as && <span className="text-xs text-[var(--text-muted)]">({data.profile.also_known_as})</span>}
          {!data.has_dld_link && <SignalBadge tone="neutral">No direct DLD match at this grain</SignalBadge>}
          {hasOwnActivity && (
            <Link to={`/communities/${data.community_key}`}>
              <SignalBadge tone="good">View full market analytics &rarr;</SignalBadge>
            </Link>
          )}
        </div>
        {data.profile?.description && <p className="text-xs text-[var(--text-muted)] mt-1 max-w-2xl">{data.profile.description}</p>}
      </div>

      <div>
        <SectionHeader title={data.child_count > 0 ? "Combined Stats (this area + all sub-areas, DLD community-level)" : "Stats (DLD community-level)"} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiCard label="Sales" value={data.subtree_stats.sales_count.toLocaleString()} />
          <KpiCard label="Sales Value" value={formatAed(data.subtree_stats.sales_value)} />
          <KpiCard label="Median Price" value={formatAed(data.subtree_stats.median_price)} />
          <KpiCard label="Rentals" value={data.subtree_stats.rental_count.toLocaleString()} />
          <KpiCard label="Median Rent" value={formatAed(data.subtree_stats.median_rent)} />
          <KpiCard
            label="Est. Gross Yield"
            value={data.subtree_stats.estimated_gross_yield_pct !== null ? formatPct(data.subtree_stats.estimated_gross_yield_pct) : "N/A"}
          />
        </div>
      </div>

      {(data.subtree_project_matched_stats.sales_count > 0 || data.subtree_project_matched_stats.rental_count > 0) && (
        <div>
          <SectionHeader title="Combined Stats (via building-level project matching)" />
          <p className="text-[10px] text-[var(--text-muted)] -mt-2 mb-2 max-w-2xl">
            DLD only reports transactions at the broad community level, never per sub-district — these figures instead trace each transaction's building
            name to its Propsearch-scraped development, which does carry a precise sub-area. Different methodology than the numbers above; may include
            occasional building-name mismatches.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard label="Sales" value={data.subtree_project_matched_stats.sales_count.toLocaleString()} />
            <KpiCard label="Sales Value" value={formatAed(data.subtree_project_matched_stats.sales_value)} />
            <KpiCard label="Median Price" value={formatAed(data.subtree_project_matched_stats.median_price)} />
            <KpiCard label="Rentals" value={data.subtree_project_matched_stats.rental_count.toLocaleString()} />
            <KpiCard label="Median Rent" value={formatAed(data.subtree_project_matched_stats.median_rent)} />
            <KpiCard
              label="Est. Gross Yield"
              value={data.subtree_project_matched_stats.estimated_gross_yield_pct !== null ? formatPct(data.subtree_project_matched_stats.estimated_gross_yield_pct) : "N/A"}
            />
          </div>
        </div>
      )}

      {data.livability && (data.livability.total_amenities > 0 || data.livability.total_schools > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card className="p-4">
            <SectionHeader title={`Amenities (${data.livability.total_amenities})`} />
            <ul className="space-y-1 text-sm">
              {data.livability.amenity_counts.map((a) => (
                <li key={a.category} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                  <span>{a.category}</span>
                  <span className="text-[var(--text-muted)]">{a.count.toLocaleString()}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-4">
            <SectionHeader title={`Schools (${data.livability.total_schools})`} />
            <ul className="space-y-1.5 text-sm max-h-64 overflow-y-auto">
              {data.livability.top_schools.map((s) => (
                <li key={s.name} className="border-b border-[var(--border)]/40 py-1">
                  <div className="flex justify-between">
                    <span>{s.name}</span>
                    {s.rating && <span className="text-[var(--text-muted)] text-xs">{s.rating}</span>}
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)]">{s.curriculum}{s.distance_text ? ` · ${s.distance_text}` : ""}</div>
                </li>
              ))}
              {data.livability.top_schools.length === 0 && <li className="text-[var(--text-muted)]">No scraped school data</li>}
            </ul>
          </Card>
        </div>
      )}

      <div>
        <SectionHeader title={`Sub-Areas (${data.child_count})`} />
        {data.children.length > 0 && (
          <p className="text-[10px] text-[var(--text-muted)] -mt-1 mb-3">
            Sales/rentals shown per sub-area are via project-name matching (see note above) — DLD doesn't report at this grain directly.
          </p>
        )}
        {data.children.length === 0 ? (
          <EmptyState title="No sub-areas" detail="This is a leaf area with no further sub-communities scraped." />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.children.map((c) => (
              <ChildCard key={c.area_id} child={c} onClick={() => navigate(`/areas/${c.area_id}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ChildCard({ child, onClick }: { child: AreaChildItem; onClick: () => void }) {
  // DLD's own area label never resolves this finely, so the direct figures
  // (child.sales_count/rental_count) are almost always zero for a sub-area —
  // the project-matched figures are the ones with real signal here.
  const pm = child.project_matched_stats;
  const sales = child.sales_count > 0 ? child.sales_count : pm.sales_count;
  const rentals = child.rental_count > 0 ? child.rental_count : pm.rental_count;
  const viaProjectMatch = child.sales_count === 0 && child.rental_count === 0 && (pm.sales_count > 0 || pm.rental_count > 0);

  return (
    <Card className="overflow-hidden cursor-pointer hover:border-[var(--accent)] transition-colors">
      <button onClick={onClick} className="block w-full text-left">
        <div className="h-24 bg-[var(--surface-2)]">
          {child.hero_image_url && (
            <img
              src={upgradeToXlImage(child.hero_image_url)}
              onError={onHeroImageError(child.hero_image_url)}
              alt={child.name}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          )}
        </div>
        <div className="p-3">
          <div className="font-medium truncate">{child.name}</div>
          <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
            {child.child_count > 0 ? `${child.child_count} sub-area${child.child_count !== 1 ? "s" : ""}` : "No further sub-areas"}
          </div>
          <div className="flex justify-between mt-2 text-xs">
            <span><span className="text-[var(--text-muted)]">Sales:</span> {sales.toLocaleString()}</span>
            <span><span className="text-[var(--text-muted)]">Rentals:</span> {rentals.toLocaleString()}</span>
          </div>
          {pm.median_price !== null && <div className="text-[10px] text-[var(--text-muted)] mt-1">Median: {formatAed(pm.median_price)}</div>}
          {viaProjectMatch && <div className="text-[9px] text-[var(--text-muted)] mt-0.5 italic">via matched projects</div>}
        </div>
      </button>
    </Card>
  );
}
