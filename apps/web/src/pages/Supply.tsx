import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, EmptyState, ErrorState, LoadingSkeleton, SectionHeader } from "../components/ui";

export function Supply() {
  const { data, isLoading, error } = useQuery({ queryKey: ["supply"], queryFn: () => api.supply() });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Supply Intelligence</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="p-4">
          <SectionHeader title="Development Status Breakdown" />
          <ul className="space-y-1 text-sm">
            {Object.entries(data.status_breakdown).map(([status, count]) => (
              <li key={status} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                <span className="capitalize">{status.replace(/_/g, " ")}</span>
                <span className="text-[var(--text-muted)]">{count}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-4">
          <SectionHeader title="Known Residential Unit Mix" />
          {data.known_units ? (
            <ul className="space-y-1 text-sm">
              {Object.entries(data.known_units).map(([k, v]) => (
                <li key={k} className="flex justify-between border-b border-[var(--border)]/40 py-1">
                  <span className="uppercase">{k}</span>
                  <span className="text-[var(--text-muted)]">{v?.toLocaleString() ?? "N/A"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No unit supply data currently available" detail="The scraper's unit_supply table has not been populated yet — this is a known gap, not an error." />
          )}
        </Card>
      </div>

      <Card className="p-4">
        <SectionHeader title="Upcoming Supply by Area (under construction / planned / announced)" />
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[var(--text-muted)] text-xs"><th className="py-1">Area</th><th className="py-1 text-right">Projects</th><th className="py-1 text-right">Units</th></tr>
          </thead>
          <tbody>
            {data.upcoming_by_area.map((row) => (
              <tr key={row.area ?? "unknown"} className="border-t border-[var(--border)]/40">
                <td className="py-1">{row.area ?? "Unknown"}</td>
                <td className="py-1 text-right">{row.projects}</td>
                <td className="py-1 text-right">{row.units?.toLocaleString() ?? "N/A"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card className="p-4">
        <SectionHeader title="Upcoming Supply by Developer" />
        <table className="w-full text-sm">
          <thead><tr className="text-left text-[var(--text-muted)] text-xs"><th className="py-1">Developer</th><th className="py-1 text-right">Projects</th></tr></thead>
          <tbody>
            {data.upcoming_by_developer.map((row) => (
              <tr key={row.developer} className="border-t border-[var(--border)]/40">
                <td className="py-1">{row.developer}</td>
                <td className="py-1 text-right">{row.projects}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
