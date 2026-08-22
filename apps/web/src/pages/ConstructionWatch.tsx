import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type ConstructionWatchItem } from "../lib/api";
import { Card, EmptyState, ErrorState, KpiCard, LoadingSkeleton, Select, SectionHeader } from "../components/ui";

const FIELD_LABELS: Record<string, string> = {
  normalized_status: "Status Change",
  raw_status: "Status Change (raw)",
  estimated_completion_date: "Completion Estimate Moved",
  actual_completion_date: "Actual Completion Recorded",
  total_units: "Unit Count Revised",
};

export function ConstructionWatch() {
  const [field, setField] = useState("");
  const { data, isLoading, error } = useQuery({
    queryKey: ["construction-watch", field],
    queryFn: () => api.constructionWatch(field || undefined, 100),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold">Construction Watch</h1>
        <p className="text-xs text-[var(--text-muted)]">
          Field-level changes detected across Propsearch re-crawls: status flips, completion-date slips, and unit-count revisions. This is a diff feed off
          the scraper's own history — not DLD data.
        </p>
      </div>

      {isLoading && <LoadingSkeleton rows={6} />}
      {error && <ErrorState message={(error as Error).message} />}
      {data && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <KpiCard label="Flipped to Completed" value={data.flipped_to_completed_total.toLocaleString()} />
            {data.watched_fields.map((f) => (
              <KpiCard key={f} label={FIELD_LABELS[f] ?? f} value={(data.field_counts[f] ?? 0).toLocaleString()} />
            ))}
          </div>

          <Card className="p-4">
            <SectionHeader
              title="Recent Changes"
              action={
                <Select
                  value={field}
                  onChange={setField}
                  options={[
                    { value: "", label: "All Change Types" },
                    ...data.watched_fields.map((f) => ({ value: f, label: FIELD_LABELS[f] ?? f })),
                  ]}
                />
              }
            />
            {data.items.length === 0 ? (
              <EmptyState title="No changes recorded for this filter" />
            ) : (
              <ul className="divide-y divide-[var(--border)]/40">
                {data.items.map((item) => (
                  <ChangeRow key={item.change_id} item={item} />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function ChangeRow({ item }: { item: ConstructionWatchItem }) {
  const label = FIELD_LABELS[item.field_name] ?? item.field_name;
  const name = item.master_project_slug ? (
    <Link to={`/projects/${item.master_project_slug}`} className="font-medium text-[var(--accent)]">{item.development_name}</Link>
  ) : (
    <span className="font-medium">{item.development_name}</span>
  );
  return (
    <li className="py-2 text-sm flex items-start justify-between gap-4">
      <div>
        {name}
        <div className="text-xs text-[var(--text-muted)]">{item.area_name ?? "Unknown area"} · {label}</div>
        <div className="text-xs mt-0.5">
          <span className="text-[var(--text-muted)]">{item.old_value ?? "—"}</span>
          <span className="mx-1.5">&rarr;</span>
          <span>{item.new_value ?? "—"}</span>
        </div>
      </div>
      <div className="text-[10px] text-[var(--text-muted)] whitespace-nowrap">{item.detected_at.slice(0, 10)}</div>
    </li>
  );
}
