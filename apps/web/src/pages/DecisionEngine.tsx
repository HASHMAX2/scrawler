import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type DecisionEngineProfile } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, LoadingSkeleton, Select, SignalBadge } from "../components/ui";
import { formatAed, formatPct } from "../lib/format";

const PRIORITY_OPTIONS = [
  { value: "balanced", label: "Balanced" },
  { value: "rental_income", label: "Rental Income" },
  { value: "capital_appreciation", label: "Capital Appreciation" },
  { value: "liquidity", label: "Liquidity" },
];
const RISK_OPTIONS = [
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "high", label: "High" },
];
const READY_OFFPLAN_OPTIONS = [
  { value: "either", label: "Either" },
  { value: "ready", label: "Ready" },
  { value: "offplan", label: "Off-Plan" },
];
const PROPERTY_TYPE_OPTIONS = [
  { value: "", label: "Any" },
  { value: "Apartment", label: "Apartment" },
  { value: "Villa", label: "Villa" },
  { value: "Townhouse", label: "Townhouse" },
  { value: "Office", label: "Office" },
  { value: "Retail", label: "Retail" },
];
const BEDROOM_OPTIONS = [
  { value: "", label: "Any" },
  { value: "Studio", label: "Studio" },
  { value: "1BR", label: "1BR" },
  { value: "2BR", label: "2BR" },
  { value: "3BR", label: "3BR" },
  { value: "4BR", label: "4BR" },
  { value: "5BR+", label: "5BR+" },
];

const RISK_TONE: Record<string, "good" | "warn" | "bad" | "neutral"> = {
  low: "good", moderate: "neutral", high: "warn", very_high: "bad", insufficient_data: "neutral",
};

export function DecisionEngine() {
  const { period } = useFilters();
  const [budgetMax, setBudgetMax] = useState("");
  const [propertyType, setPropertyType] = useState("");
  const [bedroom, setBedroom] = useState("");
  const [readyOffplan, setReadyOffplan] = useState<DecisionEngineProfile["ready_offplan"]>("either");
  const [priority, setPriority] = useState<DecisionEngineProfile["priority"]>("balanced");
  const [riskTolerance, setRiskTolerance] = useState<DecisionEngineProfile["risk_tolerance"]>("medium");
  const [submitted, setSubmitted] = useState<Omit<DecisionEngineProfile, "period"> | null>(null);

  // Respects the global period selector (top-right), same as every other
  // page — re-runs automatically if the user changes it after ranking.
  const { data, isLoading, error } = useQuery({
    queryKey: ["decision-engine", submitted, period],
    queryFn: () => api.decisionEngine({ ...submitted!, period }),
    enabled: submitted !== null,
  });

  const runSearch = () => {
    setSubmitted({
      budget_max: budgetMax ? Number(budgetMax) : undefined,
      property_type: propertyType || undefined,
      bedroom: bedroom || undefined,
      ready_offplan: readyOffplan,
      priority,
      risk_tolerance: riskTolerance,
      limit: 10,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Decision Engine</h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">
          Set an investment profile below and get communities ranked by a transparent, deterministic score. This is not financial advice — every
          score component, weight, and data gap is shown so you can judge the ranking yourself.
        </p>
      </div>

      <Card className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 items-end">
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Budget Max (AED)
          <input
            value={budgetMax}
            onChange={(e) => setBudgetMax(e.target.value)}
            placeholder="No limit"
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Property Type
          <Select value={propertyType} onChange={setPropertyType} options={PROPERTY_TYPE_OPTIONS} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Bedrooms
          <Select value={bedroom} onChange={setBedroom} options={BEDROOM_OPTIONS} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Ready / Off-Plan
          <Select value={readyOffplan!} onChange={(v) => setReadyOffplan(v as never)} options={READY_OFFPLAN_OPTIONS} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Priority
          <Select value={priority!} onChange={(v) => setPriority(v as never)} options={PRIORITY_OPTIONS} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Risk Tolerance
          <Select value={riskTolerance!} onChange={(v) => setRiskTolerance(v as never)} options={RISK_OPTIONS} />
        </label>
        <button
          onClick={runSearch}
          className="col-span-2 md:col-span-3 lg:col-span-6 bg-[var(--accent)] text-[var(--bg)] rounded px-4 py-2 text-sm font-medium"
        >
          Rank Communities
        </button>
      </Card>

      {submitted === null && <EmptyState title="Set your investment profile above and click Rank Communities" />}
      {isLoading && <LoadingSkeleton rows={6} />}
      {error && <ErrorState message={(error as Error).message} />}

      {data && (
        <>
          <Card className="p-4">
            <p className="text-xs text-[var(--text-muted)]">{data.methodology}</p>
          </Card>
          {data.results.length === 0 && <EmptyState title="No communities met the minimum sample size for this profile" detail="Try widening filters or removing the budget cap." />}
          <div className="space-y-3">
            {data.results.map((r, i) => (
              <Card key={r.community_key} className="p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-xs text-[var(--text-muted)]">#{i + 1}</div>
                    <Link to={`/communities/${encodeURIComponent(r.community_key)}`} className="text-base font-medium text-[var(--accent)]">
                      {r.community_name}
                    </Link>
                    <p className="text-xs text-[var(--text-muted)] mt-1">{r.why}</p>
                  </div>
                  <div className="text-2xl font-semibold shrink-0 ml-4">{r.score}<span className="text-xs text-[var(--text-muted)]">/100</span></div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 text-xs">
                  <div><div className="text-[var(--text-muted)]">Median Price</div><div>{formatAed(r.median_price)}</div></div>
                  <div><div className="text-[var(--text-muted)]">Median Rent</div><div>{formatAed(r.median_rent)}</div></div>
                  <div><div className="text-[var(--text-muted)]">Est. Yield</div><div>{r.estimated_gross_yield_pct !== null ? formatPct(r.estimated_gross_yield_pct) : "N/A"}</div></div>
                  <div><div className="text-[var(--text-muted)]">Liquidity</div><div>{r.liquidity.score}/100</div></div>
                </div>
                {(r.risks.length > 0 || r.missing_data.length > 0) && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {r.risks.map((risk, idx) => (
                      <SignalBadge key={`risk-${idx}`} tone={RISK_TONE[r.oversupply_risk.risk] ?? "warn"}>{risk}</SignalBadge>
                    ))}
                    {r.missing_data.map((m, idx) => (
                      <SignalBadge key={`missing-${idx}`} tone="neutral">{m}</SignalBadge>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
