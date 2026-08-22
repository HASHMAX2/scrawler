import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type CommunityDetail as CommunityDetailType } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, LoadingSkeleton, SectionHeader } from "../components/ui";
import { formatAed, formatPct } from "../lib/format";

export function Compare() {
  const { period } = useFilters();
  const [input, setInput] = useState("");
  const [keys, setKeys] = useState<string[]>([]);

  const search = useQuery({
    queryKey: ["communities-search", input],
    queryFn: () => api.communities("90d", 1, 8, "sales_count", input || undefined),
    enabled: input.length > 1,
  });

  const compare = useQuery({
    queryKey: ["compare", keys, period],
    queryFn: () => api.compare(keys, period),
    enabled: keys.length >= 2,
  });

  const addKey = (key: string) => {
    if (keys.length >= 5 || keys.includes(key)) return;
    setKeys([...keys, key]);
    setInput("");
  };
  const removeKey = (key: string) => setKeys(keys.filter((k) => k !== key));

  const rows: { label: string; get: (c: CommunityDetailType) => string }[] = [
    { label: "Sales (period)", get: (c) => c.sales.count.toLocaleString() },
    { label: "Sales Value", get: (c) => formatAed(c.sales.value) },
    { label: "Median Price", get: (c) => formatAed(c.sales.median_price) },
    { label: "Median PSF", get: (c) => (c.sales.median_psf ? `AED ${c.sales.median_psf.toFixed(0)}` : "N/A") },
    { label: "Rental Contracts", get: (c) => c.rentals.count.toLocaleString() },
    { label: "Median Rent", get: (c) => formatAed(c.rentals.median_rent) },
    { label: "Est. Gross Yield", get: (c) => (c.estimated_gross_yield_pct !== null ? formatPct(c.estimated_gross_yield_pct) : "N/A") },
    { label: "Upcoming Supply (units)", get: (c) => (c.upcoming_supply_units !== null ? c.upcoming_supply_units.toLocaleString() : "No data") },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Compare Communities</h1>
      <Card className="p-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          {keys.map((k) => (
            <span key={k} className="text-xs bg-[var(--accent-soft)] text-[var(--accent)] rounded px-2 py-1 flex items-center gap-1">
              {k}
              <button onClick={() => removeKey(k)} className="hover:text-[var(--bad)]">×</button>
            </span>
          ))}
        </div>
        {keys.length < 5 && (
          <div className="relative">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Search a community to add (2-5 total)..."
              className="w-full bg-[var(--surface-2)] border border-[var(--border)] rounded px-3 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
            />
            {search.data && search.data.items.length > 0 && input.length > 1 && (
              <div className="absolute z-10 mt-1 w-full bg-[var(--surface-2)] border border-[var(--border)] rounded shadow-lg max-h-56 overflow-y-auto">
                {search.data.items.map((item) => (
                  <button
                    key={item.community_key}
                    onClick={() => addKey(item.community_key)}
                    className="block w-full text-left px-3 py-1.5 text-sm hover:bg-[var(--hover-overlay)]"
                  >
                    {item.community_name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {keys.length < 2 && <EmptyState title="Add at least 2 communities to compare" detail="Search above and select up to 5." />}
      {compare.isLoading && <LoadingSkeleton rows={6} />}
      {compare.error && <ErrorState message={(compare.error as Error).message} />}
      {compare.data && (
        <Card className="p-4 overflow-x-auto">
          <SectionHeader title={`Side-by-Side — ${compare.data.period}`} />
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="text-left py-2 px-3 text-[var(--text-muted)]">Metric</th>
                {compare.data.items.map((c) => (
                  <th key={c.community_key} className="text-right py-2 px-3">{c.community_name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label} className="border-t border-[var(--border)]/50">
                  <td className="py-2 px-3 text-[var(--text-muted)]">{row.label}</td>
                  {compare.data!.items.map((c) => (
                    <td key={c.community_key} className="py-2 px-3 text-right">{row.get(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
