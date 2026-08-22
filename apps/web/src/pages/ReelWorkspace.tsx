import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type ReelEntity, type ReelRunResult } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, LoadingSkeleton, SectionHeader, SignalBadge } from "../components/ui";
import { formatReelMetric } from "../lib/format";

const STATUS_TONE: Record<string, "good" | "warn" | "neutral"> = { ready: "good", partial: "warn", external: "neutral" };

const BEDROOM_OPTIONS = ["Studio", "1BR", "2BR", "3BR", "4BR", "5BR+"];

function useCommunityOptions(period: string) {
  return useQuery({
    queryKey: ["communities-all", period],
    queryFn: () => api.communities(period, 1, 200),
    select: (d) => [...d.items].sort((a, b) => a.community_name.localeCompare(b.community_name)),
    staleTime: 5 * 60_000,
  });
}

function CommunitySelect({ value, onChange, label, period }: { value: string; onChange: (v: string) => void; label: string; period: string }) {
  const { data } = useCommunityOptions(period);
  return (
    <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] min-w-[180px]"
      >
        <option value="">Most active community</option>
        {data?.map((c) => (
          <option key={c.community_key} value={c.community_key}>{c.community_name}</option>
        ))}
      </select>
    </label>
  );
}

function ProjectSelect({ value, onChange, availableProjects, period }: { value: string; onChange: (v: string) => void; availableProjects: string[] | undefined; period: string }) {
  const { data } = useQuery({
    queryKey: ["projects-picker", period],
    queryFn: () => api.projects(undefined, period, 200),
    staleTime: 5 * 60_000,
  });
  const nameBySlug = new Map((data?.items ?? []).filter((p) => p.master_slug).map((p) => [p.master_slug as string, p.name] as const));
  return (
    <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
      Project
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)] min-w-[200px]"
      >
        <option value="">Largest project</option>
        {(availableProjects ?? []).map((slug) => (
          <option key={slug} value={slug}>{nameBySlug.get(slug) ?? slug.replace(/-/g, " ")}</option>
        ))}
      </select>
    </label>
  );
}

function ParamsPanel({
  resolver, params, setParam, period, availableProjects,
}: {
  resolver: string;
  params: Record<string, string>;
  setParam: (key: string, value: string) => void;
  period: string;
  availableProjects?: string[];
}) {
  if (resolver === "project_scorecard") {
    return <ProjectSelect value={params.project ?? ""} onChange={(v) => setParam("project", v)} availableProjects={availableProjects} period={period} />;
  }
  if (resolver === "community_comparison") {
    return (
      <div className="flex flex-wrap gap-3">
        <CommunitySelect label="Community A" value={params.communityA ?? ""} onChange={(v) => setParam("communityA", v)} period={period} />
        <CommunitySelect label="Community B" value={params.communityB ?? ""} onChange={(v) => setParam("communityB", v)} period={period} />
      </div>
    );
  }
  if (resolver === "supply_analysis" || resolver === "building_insight" || resolver === "psf_ranking") {
    return (
      <div className="flex flex-wrap gap-3 items-end">
        <CommunitySelect label="Community" value={params.community ?? ""} onChange={(v) => setParam("community", v)} period={period} />
        {resolver === "building_insight" && (
          <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
            Kind
            <select
              value={params.kind ?? "rentals"}
              onChange={(e) => setParam("kind", e.target.value)}
              className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
            >
              <option value="rentals">Most rented</option>
              <option value="sales">Most traded</option>
            </select>
          </label>
        )}
      </div>
    );
  }
  if (resolver === "yield_ranking") {
    return (
      <div className="flex flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Bedroom
          <select
            value={params.bedroom ?? ""}
            onChange={(e) => setParam("bedroom", e.target.value)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">Any</option>
            {BEDROOM_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Max Budget (AED)
          <input
            type="number" placeholder="No limit" value={params.budgetMax ?? ""}
            onChange={(e) => setParam("budgetMax", e.target.value)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm w-36 focus:outline-none focus:border-[var(--accent)]"
          />
        </label>
      </div>
    );
  }
  if (resolver === "budget_explorer") {
    return (
      <div className="flex flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Budget (AED)
          <input
            type="number" value={params.budget ?? "1000000"}
            onChange={(e) => setParam("budget", e.target.value)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm w-40 focus:outline-none focus:border-[var(--accent)]"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--text-muted)]">
          Bedroom
          <select
            value={params.bedroom ?? ""}
            onChange={(e) => setParam("bedroom", e.target.value)}
            className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1.5 text-sm focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">Any</option>
            {BEDROOM_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
      </div>
    );
  }
  return null;
}

function EntityCard({ entity }: { entity: ReelEntity }) {
  return (
    <Card className="p-4">
      <div className="font-medium">{entity.label}</div>
      {entity.subtitle && <div className="text-xs text-[var(--text-muted)] mt-0.5">{entity.subtitle}</div>}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
        {entity.metrics.map((m) => (
          <div key={m.label}>
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide">{m.label}</div>
            <div className={`text-sm font-medium ${m.tone === "good" ? "text-[var(--good)]" : m.tone === "bad" ? "text-[var(--bad)]" : ""}`}>
              {formatReelMetric(m.value, m.format)}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function RankingTable({ entities }: { entities: ReelEntity[] }) {
  if (entities.length === 0) return <EmptyState title="No entities meet the minimum sample size for this period" />;
  const metricLabels = entities[0].metrics.map((m) => m.label);
  return (
    <Card className="p-4 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            <th className="text-left py-2 px-3 text-[var(--text-muted)]">#</th>
            <th className="text-left py-2 px-3 text-[var(--text-muted)]">Entity</th>
            {metricLabels.map((l) => <th key={l} className="text-right py-2 px-3 text-[var(--text-muted)]">{l}</th>)}
          </tr>
        </thead>
        <tbody>
          {entities.map((e, i) => (
            <tr key={e.id} className="border-t border-[var(--border)]/50">
              <td className="py-2 px-3 text-[var(--text-muted)]">{i + 1}</td>
              <td className="py-2 px-3 font-medium">{e.label}<div className="text-[10px] text-[var(--text-muted)] font-normal">{e.subtitle}</div></td>
              {e.metrics.map((m) => (
                <td key={m.label} className={`py-2 px-3 text-right ${m.tone === "good" ? "text-[var(--good)]" : m.tone === "bad" ? "text-[var(--bad)]" : ""}`}>
                  {formatReelMetric(m.value, m.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function generateScript(result: ReelRunResult, duration: 30 | 45 | 60): string {
  const hook = result.whatIsInteresting ?? result.question;
  const factCount = duration === 30 ? 2 : duration === 45 ? 3 : 5;
  // The hook is usually drawn from the same fact-generation logic as the
  // first Reel Ready Fact — skip it here so the script doesn't say the same
  // sentence twice in a row.
  const facts = result.reelReadyFacts.filter((f) => f !== hook).slice(0, factCount);
  const verdictLine = result.verdict?.length
    ? `Bottom line: ${result.verdict.filter((v) => v.winner).map((v) => `${v.dimension} goes to ${v.winner}`).join(". ")}.`
    : null;

  const blocks = [
    `HOOK\n${hook}.`,
    `DATA POINT\n${facts[0] ?? ""}`,
    facts.length > 1 ? `CONTRAST\n${facts.slice(1).join(" ")}` : null,
    verdictLine ? `VERDICT\n${verdictLine}` : null,
    `CAVEAT\n${result.caveat}`,
  ].filter((b): b is string => Boolean(b));

  return blocks.join("\n\n");
}

export function ReelWorkspace() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const { period } = useFilters();
  const [params, setParams] = useState<Record<string, string>>(() => Object.fromEntries(searchParams.entries()));
  const [scriptDuration, setScriptDuration] = useState<30 | 45 | 60>(45);
  const [showScript, setShowScript] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const reelId = Number(id);
  const setParam = (key: string, value: string) => setParams((p) => ({ ...p, [key]: value }));

  const run = useQuery({
    queryKey: ["reel-run", reelId, period, params],
    queryFn: () => api.runReel(reelId, { period, ...params }),
    enabled: Number.isFinite(reelId),
  });

  const copy = (text: string, what: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(what);
      setTimeout(() => setCopied(null), 1500);
    });
  };

  const factsText = useMemo(() => run.data?.reelReadyFacts.map((f) => `• ${f}`).join("\n") ?? "", [run.data]);

  if (!Number.isFinite(reelId)) return <ErrorState message="Invalid reel id" />;
  if (run.isLoading) return <LoadingSkeleton rows={8} />;
  if (run.error) return <ErrorState message={(run.error as Error).message} />;
  if (!run.data) return null;

  const reel = run.data.reel;
  const isRanking = run.data.entities.length > 3 && !run.data.verdict;

  return (
    <div className="space-y-5 max-w-5xl">
      <div>
        <Link to="/reels" className="text-xs text-[var(--text-muted)] hover:text-[var(--text)]">&larr; Reels</Link>
        <div className="flex items-start justify-between gap-3 mt-1">
          <div>
            <div className="text-[10px] text-[var(--text-muted)] font-mono">#{reel.id}</div>
            <h1 className="text-lg font-semibold uppercase leading-snug">{reel.title}</h1>
            <div className="text-xs text-[var(--text-muted)] mt-1">
              {reel.category.replace(/^"|"$/g, "")}{reel.franchise ? ` · ${reel.franchise}` : ""}
            </div>
          </div>
          <SignalBadge tone={STATUS_TONE[run.data.status]}>{run.data.status === "ready" ? "Ready" : run.data.status === "partial" ? "Partial" : "External Source Required"}</SignalBadge>
        </div>
      </div>

      <Card className="p-4">
        <ParamsPanel resolver={reel.resolver} params={params} setParam={setParam} period={period} availableProjects={run.data.availableProjects} />
      </Card>

      <Card className="p-4">
        <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mb-1.5">The Question</div>
        <div className="text-base">{run.data.question}</div>
      </Card>

      {run.data.status === "external" || (run.data.status === "partial" && run.data.entities.length === 0) ? (
        <Card className="p-4 border-[var(--warn)]/40">
          <div className="text-sm font-medium text-[var(--warn)] mb-1">
            {run.data.status === "external" ? "External Source Required" : "Partial Data"}
          </div>
          <p className="text-sm text-[var(--text-muted)]">{run.data.caveat}</p>
        </Card>
      ) : (
        <>
          <div>
            <SectionHeader title="Key Answer" />
            {isRanking ? (
              <RankingTable entities={run.data.entities} />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {run.data.entities.map((e) => <EntityCard key={e.id} entity={e} />)}
              </div>
            )}
          </div>

          {run.data.verdict && run.data.verdict.length > 0 && (
            <div>
              <SectionHeader title="Verdict" />
              <Card className="p-4">
                <table className="w-full text-sm">
                  <tbody>
                    {run.data.verdict.map((v) => (
                      <tr key={v.dimension} className="border-b border-[var(--border)]/50 last:border-0">
                        <td className="py-1.5 pr-3 text-[var(--text-muted)]">{v.dimension}</td>
                        <td className="py-1.5 pr-3 font-medium text-[var(--accent)]">{v.winner ?? "—"}</td>
                        <td className="py-1.5 text-[var(--text-muted)] text-xs">{v.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          )}

          {run.data.whatIsInteresting && (
            <div>
              <SectionHeader title="Why?" />
              <Card className="p-4 text-sm">{run.data.whatIsInteresting}</Card>
            </div>
          )}

          {run.data.reelReadyFacts.length > 0 && (
            <div>
              <SectionHeader
                title="Reel Ready Facts"
                action={
                  <button onClick={() => copy(factsText, "facts")} className="text-xs text-[var(--accent)] hover:underline">
                    {copied === "facts" ? "Copied" : "Copy Facts"}
                  </button>
                }
              />
              <Card className="p-4">
                <ul className="space-y-1.5 text-sm list-disc list-inside">
                  {run.data.reelReadyFacts.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
              </Card>
            </div>
          )}

          <Card className="p-4 border-[var(--border)]">
            <div className="text-xs text-[var(--text-muted)]">
              <span className="font-medium text-[var(--text)]">Caveat:</span> {run.data.caveat}
            </div>
            <div className="text-xs text-[var(--text-muted)] mt-2">
              <span className="font-medium text-[var(--text)]">Source:</span> {reel.sourceLabels.join(", ")} · Period: {run.data.period} · Calculated just now
            </div>
          </Card>

          <div>
            <SectionHeader
              title="Generate Reel Script"
              action={
                <div className="flex items-center gap-2">
                  {([30, 45, 60] as const).map((d) => (
                    <button
                      key={d}
                      onClick={() => setScriptDuration(d)}
                      className={`text-xs rounded-full px-2.5 py-1 border ${scriptDuration === d ? "bg-[var(--accent)] text-[var(--bg)] border-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)]"}`}
                    >
                      {d}s
                    </button>
                  ))}
                  <button
                    onClick={() => setShowScript((s) => !s)}
                    className="text-xs bg-[var(--accent-soft)] text-[var(--accent)] rounded px-2.5 py-1 hover:opacity-80"
                  >
                    {showScript ? "Hide" : "Generate"}
                  </button>
                </div>
              }
            />
            {showScript && (
              <Card className="p-4">
                <pre className="text-sm whitespace-pre-wrap font-sans">{generateScript(run.data, scriptDuration)}</pre>
                <button
                  onClick={() => copy(generateScript(run.data!, scriptDuration), "script")}
                  className="text-xs text-[var(--accent)] hover:underline mt-3"
                >
                  {copied === "script" ? "Copied" : "Copy Script"}
                </button>
              </Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}
