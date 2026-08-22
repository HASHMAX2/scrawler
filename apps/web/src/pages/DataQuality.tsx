import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, ErrorState, LoadingSkeleton, SectionHeader, Select, SignalBadge } from "../components/ui";

const CONFIDENCE_TONE: Record<string, "good" | "bad" | "warn" | "neutral"> = {
  exact: "good", fuzzy_high: "good", scraped_only: "neutral", fuzzy_low: "warn", unmatched: "bad",
};

export function DataQuality() {
  const { data, isLoading, error } = useQuery({ queryKey: ["data-quality"], queryFn: () => api.dataQuality() });
  const [reviewType, setReviewType] = useState<"area" | "project">("area");
  const review = useQuery({ queryKey: ["review-queue", reviewType], queryFn: () => api.reviewQueue(reviewType, 100) });

  if (isLoading) return <LoadingSkeleton rows={8} />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Data Quality</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card className="p-4">
          <SectionHeader title="Area Match Confidence" />
          <ConfidenceBar counts={data.area_match_confidence} />
        </Card>
        <Card className="p-4">
          <SectionHeader title="Project Match Confidence" />
          <ConfidenceBar counts={data.project_match_confidence} />
        </Card>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <Card className="p-4"><div className="text-[var(--text-muted)] text-xs">Unmatched project sales rows</div><div className="text-xl">{data.unmatched_project_sales_rows.toLocaleString()}</div></Card>
        <Card className="p-4"><div className="text-[var(--text-muted)] text-xs">Unmatched project rental rows</div><div className="text-xl">{data.unmatched_project_rental_rows.toLocaleString()}</div></Card>
        <Card className="p-4"><div className="text-[var(--text-muted)] text-xs">Invalid price rows</div><div className="text-xl">{data.invalid_price_rows.toLocaleString()}</div></Card>
        <Card className="p-4"><div className="text-[var(--text-muted)] text-xs">Invalid rent rows</div><div className="text-xl">{data.invalid_rent_rows.toLocaleString()}</div></Card>
      </div>

      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide">Review Queue (fuzzy_low matches — not auto-linked)</h2>
          <Select value={reviewType} onChange={(v) => setReviewType(v as "area" | "project")} options={[{ value: "area", label: "Areas" }, { value: "project", label: "Projects" }]} />
        </div>
        <div className="max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--text-muted)] text-xs">
                <th className="py-1">Raw Name</th>
                <th className="py-1 text-right">Match Score</th>
              </tr>
            </thead>
            <tbody>
              {review.data?.items.map((item) => (
                <tr key={item.raw_key} className="border-t border-[var(--border)]/40">
                  <td className="py-1">{item.raw_name}</td>
                  <td className="py-1 text-right">{item.match_score.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {review.data?.items.length === 0 && <div className="text-xs text-[var(--text-muted)] py-4">Nothing awaiting review.</div>}
        </div>
      </Card>

      <Card className="p-4">
        <SectionHeader title={`Propsearch Transaction Cross-Check (${data.scraped_cross_check.matched_to_development.toLocaleString()} of ${data.scraped_cross_check.total_scraped_transactions.toLocaleString()} scraped transactions matched to a development)`} />
        <p className="text-xs text-[var(--text-muted)] mb-3">{data.scraped_cross_check.note}</p>
        {data.scraped_cross_check.projects_compared.length === 0 ? (
          <div className="text-xs text-[var(--text-muted)]">No projects with enough matched scraped transactions to compare.</div>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[var(--text-muted)] text-xs">
                  <th className="py-1">Development</th>
                  <th className="py-1 text-right">Scraped (n)</th>
                  <th className="py-1 text-right">Scraped Median</th>
                  <th className="py-1 text-right">DLD (n)</th>
                  <th className="py-1 text-right">DLD Median</th>
                  <th className="py-1 text-right">Diff</th>
                </tr>
              </thead>
              <tbody>
                {data.scraped_cross_check.projects_compared.map((p) => (
                  <tr key={p.development_name} className="border-t border-[var(--border)]/40">
                    <td className="py-1">{p.development_name}</td>
                    <td className="py-1 text-right">{p.scraped_transaction_count}</td>
                    <td className="py-1 text-right">{p.scraped_median_price?.toLocaleString() ?? "—"}</td>
                    <td className="py-1 text-right">{p.dld_transaction_count}</td>
                    <td className="py-1 text-right">{p.dld_median_price?.toLocaleString() ?? "—"}</td>
                    <td className="py-1 text-right">
                      {p.median_price_diff_pct !== null ? (
                        <SignalBadge tone={Math.abs(p.median_price_diff_pct) > 25 ? "warn" : "neutral"}>
                          {p.median_price_diff_pct > 0 ? "+" : ""}{p.median_price_diff_pct.toFixed(1)}%
                        </SignalBadge>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="p-4">
        <SectionHeader title="Files Imported" />
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[var(--text-muted)] text-xs">
              <th className="py-1">File</th><th className="py-1">Type</th><th className="py-1 text-right">Rows</th><th className="py-1">Imported</th><th className="py-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.files_imported.map((f) => (
              <tr key={f.file_path} className="border-t border-[var(--border)]/40">
                <td className="py-1 truncate max-w-xs" title={f.file_path}>{f.file_path.split("\\").pop()}</td>
                <td className="py-1">{f.dataset_type}</td>
                <td className="py-1 text-right">{f.row_count.toLocaleString()}</td>
                <td className="py-1">{f.imported_at?.slice(0, 19) ?? "—"}</td>
                <td className="py-1">{f.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function ConfidenceBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  return (
    <div>
      <div className="flex h-3 rounded overflow-hidden mb-2">
        {Object.entries(counts).map(([k, v]) => (
          <div key={k} style={{ width: `${(v / total) * 100}%` }} className={
            k === "exact" || k === "fuzzy_high" ? "bg-[var(--good)]" : k === "fuzzy_low" ? "bg-[var(--warn)]" : k === "unmatched" ? "bg-[var(--bad)]" : "bg-[var(--text-muted)]"
          } />
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(counts).map(([k, v]) => (
          <SignalBadge key={k} tone={CONFIDENCE_TONE[k] ?? "neutral"}>{k}: {v}</SignalBadge>
        ))}
      </div>
    </div>
  );
}
