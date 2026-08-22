import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type AreaListItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, LoadingSkeleton } from "../components/ui";
import { formatAed, formatPct, onHeroImageError, upgradeToXlImage } from "../lib/format";

export function Areas() {
  const { period } = useFilters();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const { data, isLoading, error } = useQuery({ queryKey: ["areas", period], queryFn: () => api.areas(period) });

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLowerCase();
    if (!q) return data.items;
    return data.items.filter((a) => a.name.toLowerCase().includes(q) || a.also_known_as?.toLowerCase().includes(q));
  }, [data, search]);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold">Areas</h1>
          <p className="text-sm text-[var(--text-muted)] mt-0.5">
            {data ? `${data.items.length} Dubai areas` : "Loading..."} — each rolls up DLD sales/rental activity across all of its sub-communities.
            Click into an area to browse its sub-areas.
          </p>
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search area..."
          className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)] w-56"
        />
      </div>
      {isLoading && <LoadingSkeleton rows={8} />}
      {error && <ErrorState message={(error as Error).message} />}
      {data && filtered.length === 0 && <EmptyState title="No areas match your search" detail={`No area name or alias matches "${search}".`} />}
      {data && filtered.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((a) => (
            <AreaCard key={a.area_id} area={a} onClick={() => navigate(`/areas/${a.area_id}`)} />
          ))}
        </div>
      )}
    </div>
  );
}

function AreaCard({ area, onClick }: { area: AreaListItem; onClick: () => void }) {
  return (
    <Card className="overflow-hidden cursor-pointer hover:border-[var(--accent)] transition-colors" >
      <button onClick={onClick} className="block w-full text-left">
        <div className="h-40 bg-[var(--surface-2)]">
          {area.hero_image_url && (
            <img
              src={upgradeToXlImage(area.hero_image_url)}
              onError={onHeroImageError(area.hero_image_url)}
              alt={area.name}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          )}
        </div>
        <div className="p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="font-medium truncate">{area.name}</div>
            {area.also_known_as && <span className="text-[10px] text-[var(--text-muted)] shrink-0">({area.also_known_as})</span>}
          </div>
          <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
            {area.child_count} sub-area{area.child_count !== 1 ? "s" : ""}
            {area.descendant_count > area.child_count ? ` · ${area.descendant_count} total nested` : ""}
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 mt-2 text-xs">
            <div><span className="text-[var(--text-muted)]">Sales:</span> {area.sales_count.toLocaleString()}</div>
            <div><span className="text-[var(--text-muted)]">Rentals:</span> {area.rental_count.toLocaleString()}</div>
            <div><span className="text-[var(--text-muted)]">Median:</span> {formatAed(area.median_price)}</div>
            <div><span className="text-[var(--text-muted)]">Yield:</span> {area.estimated_gross_yield_pct !== null ? formatPct(area.estimated_gross_yield_pct) : "N/A"}</div>
          </div>
        </div>
      </button>
    </Card>
  );
}
