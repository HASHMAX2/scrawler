import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type OpportunityItem } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, LoadingSkeleton, SectionHeader } from "../components/ui";

function OpportunityList({ items }: { items: OpportunityItem[] }) {
  if (items.length === 0) return <EmptyState title="No communities meet this signal's sample-size threshold this period" />;
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.community_key}>
          <Link
            to={`/communities/${encodeURIComponent(item.community_key)}`}
            className="group block border border-[var(--border)] hover:border-[var(--accent)] hover:bg-[var(--surface-2)] rounded p-3 transition-colors"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium group-hover:text-[var(--accent)] transition-colors">{item.community_name}</span>
              <span className="text-[var(--text-muted)] group-hover:text-[var(--accent)] transition-colors shrink-0" aria-hidden="true">&rarr;</span>
            </div>
            <p className="text-xs text-[var(--text-muted)] mt-1">{item.why}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function Opportunities() {
  const { period } = useFilters();
  const { data, isLoading, error } = useQuery({ queryKey: ["opportunities", period], queryFn: () => api.opportunities(period) });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Opportunities</h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">{data.methodology}</p>
      </div>

      <Card className="p-4">
        <SectionHeader title="High Yield + High Rental Demand" />
        <OpportunityList items={data.high_yield_high_demand} />
      </Card>
      <Card className="p-4">
        <SectionHeader title="Rising Sales Momentum" />
        <OpportunityList items={data.rising_sales_momentum} />
      </Card>
      <Card className="p-4">
        <SectionHeader title="Rental Growth Outpacing Price Growth" />
        <OpportunityList items={data.rental_growth_outpacing_price} />
      </Card>
    </div>
  );
}
