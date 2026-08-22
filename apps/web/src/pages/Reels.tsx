import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useFilters } from "../state/FilterContext";
import { Card, EmptyState, ErrorState, LoadingSkeleton, SectionHeader, SignalBadge } from "../components/ui";

const STATUS_LABEL: Record<string, string> = { ready: "Ready", partial: "Partial", external: "External Source Required" };
const STATUS_TONE: Record<string, "good" | "warn" | "neutral"> = { ready: "good", partial: "warn", external: "neutral" };

export function Reels() {
  const { period } = useFilters();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["reels", search, category, status],
    queryFn: () => api.reels({ search: search || undefined, category: category || undefined, status: status || undefined }),
  });
  const franchises = useQuery({ queryKey: ["reel-franchises"], queryFn: () => api.reelFranchises() });
  const ready = useQuery({ queryKey: ["ready-to-make", period], queryFn: () => api.readyToMake(period, 8) });

  const counts = list.data?.counts;
  const updatedThisWeek = 0; // static dataset — nothing "refreshes" independently yet

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Reel Intelligence</h1>
        <p className="text-sm text-[var(--text-muted)] mt-0.5">Turn Dubai property data into content.</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          ["235", "Reel Ideas"],
          ["6", "Content Franchises"],
          ["15", "Analysis Categories"],
          [String(counts?.ready ?? "…"), "Ready Now"],
          [String(counts?.partial ?? "…"), "Partial Data"],
          [String(updatedThisWeek), "Updated This Week"],
        ].map(([value, label]) => (
          <Card key={label} className="p-3 text-center">
            <div className="text-xl font-semibold">{value}</div>
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wide mt-0.5">{label}</div>
          </Card>
        ))}
      </div>

      <div>
        <SectionHeader title="Ready to Make" />
        {ready.isLoading && <LoadingSkeleton rows={3} />}
        {ready.error && <ErrorState message={(ready.error as Error).message} />}
        {ready.data && ready.data.items.length === 0 && (
          <EmptyState title="No standout findings this period" detail="Try a longer period, or browse the full library below." />
        )}
        {ready.data && ready.data.items.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {ready.data.items.map((item, i) => (
              <Card key={i} className="p-4">
                <div className="text-sm">🔥 {item.finding}</div>
                <div className="flex flex-wrap gap-1.5 mt-2.5">
                  {item.suggestedReels.map((r) => (
                    <Link
                      key={r.id}
                      to={`/reels/${r.id}${item.communityKey ? `?community=${encodeURIComponent(item.communityKey)}&communityA=${encodeURIComponent(item.communityKey)}` : ""}`}
                      className="text-xs bg-[var(--accent-soft)] text-[var(--accent)] rounded px-2 py-1 hover:opacity-80"
                    >
                      #{r.id} {r.title.length > 40 ? r.title.slice(0, 40) + "…" : r.title}
                    </Link>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      <div>
        <SectionHeader title="Content Franchises" />
        {franchises.isLoading && <LoadingSkeleton rows={2} />}
        {franchises.data && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {franchises.data.items.map((f) => (
              <Card key={f.name} className="p-4 flex flex-col gap-2">
                <div className="font-medium">{f.name}</div>
                <p className="text-xs text-[var(--text-muted)] flex-1">{f.description}</p>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[var(--text-muted)]">{f.readyCount}/{f.count} ready</span>
                  <button
                    onClick={() => { setCategory(null); setSearch(""); setStatus(null); document.getElementById("reel-library")?.scrollIntoView({ behavior: "smooth" }); }}
                    className="text-[var(--accent)] hover:underline"
                  >
                    View reels &rarr;
                  </button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      <div id="reel-library">
        <SectionHeader
          title="Complete Reel Library"
          action={
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search JVC, yield, developer, off-plan..."
              className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-3 py-1.5 text-sm w-72 focus:outline-none focus:border-[var(--accent)]"
            />
          }
        />

        <div className="flex flex-wrap gap-1.5 mb-3">
          <button
            onClick={() => setCategory(null)}
            className={`text-xs rounded-full px-3 py-1 border ${!category ? "bg-[var(--accent)] text-[var(--bg)] border-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]"}`}
          >
            All ({list.data?.total ?? "…"})
          </button>
          {list.data?.categories.map((c) => (
            <button
              key={c.name}
              onClick={() => setCategory(category === c.name ? null : c.name)}
              className={`text-xs rounded-full px-3 py-1 border ${category === c.name ? "bg-[var(--accent)] text-[var(--bg)] border-[var(--accent)]" : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]"}`}
            >
              {c.name.replace(/^"|"$/g, "")} ({c.count})
            </button>
          ))}
        </div>

        <div className="flex gap-1.5 mb-4">
          {(["ready", "partial", "external"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatus(status === s ? null : s)}
              className={`text-xs rounded px-2.5 py-1 border ${status === s ? "border-[var(--accent)]" : "border-[var(--border)]"}`}
            >
              <SignalBadge tone={STATUS_TONE[s]}>{STATUS_LABEL[s]}</SignalBadge>
            </button>
          ))}
        </div>

        {list.isLoading && <LoadingSkeleton rows={10} />}
        {list.error && <ErrorState message={(list.error as Error).message} />}
        {list.data && list.data.items.length === 0 && <EmptyState title="No reels match your filters" />}
        {list.data && list.data.items.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {list.data.items.map((r) => (
              <Link key={r.id} to={`/reels/${r.id}`} className="block">
                <Card className="p-3.5 h-full hover:border-[var(--accent)] transition-colors">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">#{r.id}</span>
                    <SignalBadge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</SignalBadge>
                  </div>
                  <div className="text-sm font-medium mt-1.5 uppercase leading-snug">{r.title}</div>
                  <div className="text-[11px] text-[var(--text-muted)] mt-1.5">{r.category.replace(/^"|"$/g, "")}</div>
                  <div className="text-[11px] text-[var(--text-muted)] mt-1">
                    Requires: {r.sourceLabels.join(", ")}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
