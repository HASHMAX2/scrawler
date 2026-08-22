import { AnimatePresence, motion } from "framer-motion";
import { Link } from "react-router-dom";
import type { IntelNode } from "../../lib/graph";
import type { AreaChildItem, AreaListItem, AreaProjectItem } from "../../lib/api";

const TYPE_LABEL: Record<IntelNode["type"], string> = {
  market: "Market",
  area: "Area",
  project: "Project",
  building: "Building",
  unitType: "Unit Type",
  developer: "Developer",
};

const TYPE_COLOR: Record<IntelNode["type"], string> = {
  market: "var(--node-market)",
  area: "var(--node-area)",
  project: "var(--node-project)",
  developer: "var(--node-developer)",
  building: "var(--node-infra)",
  unitType: "var(--node-unittype)",
};

function deepLinkFor(node: IntelNode): { to: string; label: string } | null {
  if (node.type === "area") {
    const raw = node.raw as AreaListItem | AreaChildItem;
    return { to: `/areas/${raw.area_id}`, label: "Open full area intelligence" };
  }
  if (node.type === "project") {
    const raw = node.raw as AreaProjectItem;
    return { to: `/projects/${raw.slug}`, label: "Open Project Intelligence" };
  }
  if (node.type === "building") {
    const raw = node.raw as { building: { slug: string } };
    const parentProjectSlug = node.parentId?.startsWith("project:") ? node.parentId.slice("project:".length) : null;
    if (parentProjectSlug) return { to: `/projects/${parentProjectSlug}/buildings/${raw.building.slug}`, label: "Open Building Intelligence" };
  }
  return null;
}

function insightFor(node: IntelNode): string | null {
  const y = node.metrics.find((m) => m.label === "Est. Yield");
  const sales = node.metrics.find((m) => m.label === "Sales");
  if (node.type === "area" && y && y.tone !== "neutral" && sales) {
    if (y.tone === "good") {
      return `${node.name} is showing an estimated gross yield of ${y.value}, above the market's typical range, across ${sales.value} matched sales transactions this period.`;
    }
    if (y.tone === "bad") {
      return `${node.name}'s estimated gross yield of ${y.value} sits below the market's typical range this period, based on ${sales.value} matched sales transactions.`;
    }
  }
  if (node.type === "project" && y && sales && sales.value !== "0") {
    return `${node.name} recorded ${sales.value} sales this period${y.tone === "good" ? ` at an estimated yield of ${y.value}` : ""}.`;
  }
  return null;
}

export function IntelPanel({ node, children }: { node: IntelNode | null; children: IntelNode[] }) {
  return (
    <div className="h-full flex flex-col border-l border-[var(--border)] bg-[var(--surface)]/80 backdrop-blur-sm">
      <AnimatePresence mode="wait">
        {node ? (
          <motion.div
            key={node.id}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.28 }}
            className="flex-1 overflow-y-auto p-5 space-y-5"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ background: TYPE_COLOR[node.type] }} />
                <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">{TYPE_LABEL[node.type]}</span>
              </div>
              <h2 className="text-lg font-semibold tracking-tight mt-1" style={{ fontFamily: "var(--font-display)" }}>
                {node.name}
              </h2>
              {node.subtitle && node.type !== "area" && <p className="text-xs text-[var(--text-muted)] mt-0.5">{node.subtitle}</p>}
            </div>

            {node.metrics.length > 0 && (
              <div className="grid grid-cols-2 gap-2.5">
                {node.metrics.map((m) => (
                  <div key={m.label} className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2.5">
                    <div className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{m.label}</div>
                    <div
                      className="text-sm font-semibold mt-0.5"
                      style={{ color: m.tone === "good" ? "var(--good)" : m.tone === "bad" ? "var(--bad)" : "var(--text)" }}
                    >
                      {m.value}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {insightFor(node) && (
              <div className="rounded-lg border border-[var(--accent)]/25 bg-[var(--accent-soft)] p-3">
                <div className="text-[10px] uppercase tracking-widest text-[var(--accent)] mb-1">AI Market Signal</div>
                <p className="text-xs leading-relaxed text-[var(--text)]">{insightFor(node)}</p>
              </div>
            )}

            {children.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] mb-2">Connected Intelligence</div>
                <ul className="space-y-1.5">
                  {children.slice(0, 6).map((c) => (
                    <li key={c.id} className="flex items-center justify-between text-xs border-b border-[var(--border)]/40 pb-1.5">
                      <span className="flex items-center gap-1.5 truncate">
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: TYPE_COLOR[c.type] }} />
                        <span className="truncate">{c.name}</span>
                      </span>
                      {c.badge && <span className="text-[var(--text-muted)] shrink-0 ml-2">{c.badge}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {deepLinkFor(node) && (
              <Link
                to={deepLinkFor(node)!.to}
                className="block text-center text-xs font-medium rounded-lg border border-[var(--border)] py-2.5 hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                {deepLinkFor(node)!.label} &rarr;
              </Link>
            )}
          </motion.div>
        ) : (
          <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 flex items-center justify-center p-6 text-center">
            <p className="text-xs text-[var(--text-muted)] max-w-[200px]">Select a node to reveal its connected intelligence.</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
