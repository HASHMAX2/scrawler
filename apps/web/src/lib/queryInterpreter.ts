/**
 * Local heuristic interpreter for the Intelligence Map query bar. This is
 * NOT an LLM — it's a small set of pattern matchers that operate on the
 * nodes currently loaded in the graph (real API data already fetched),
 * so results are always grounded in real numbers rather than generated
 * text. It's built as a swappable module: `runQuery` is the seam an actual
 * Dubai-real-estate LLM backend can replace later without touching the
 * graph or panel components that call it.
 */
import type { IntelNode } from "./graph";

export interface QueryResult {
  matchedIds: string[];
  explanation: string;
}

function parseMetric(node: IntelNode, label: string): number | null {
  const m = node.metrics.find((x) => x.label === label);
  if (!m) return null;
  const n = parseFloat(m.value.replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : null;
}

export function runQuery(rawQuery: string, visibleNodes: IntelNode[]): QueryResult {
  const q = rawQuery.trim().toLowerCase();
  if (!q) return { matchedIds: [], explanation: "" };

  const yieldMatch = q.match(/yield[^0-9]*(\d+(?:\.\d+)?)/);
  if (yieldMatch) {
    const threshold = parseFloat(yieldMatch[1]);
    const above = q.includes("under") || q.includes("below") || q.includes("<");
    const matches = visibleNodes.filter((n) => {
      const y = parseMetric(n, "Est. Yield");
      if (y === null) return false;
      return above ? y < threshold : y >= threshold;
    });
    return {
      matchedIds: matches.map((m) => m.id),
      explanation: matches.length
        ? `${matches.length} node${matches.length === 1 ? "" : "s"} in the current view ${above ? "below" : "at or above"} ${threshold}% estimated yield: ${matches.map((m) => m.name).join(", ")}.`
        : `No nodes currently in view have a calculated yield ${above ? "below" : "at or above"} ${threshold}%. Expand into more areas to widen the search.`,
    };
  }

  const compareMatch = q.match(/compare (.+?) (?:with|and|vs\.?|versus) (.+)/);
  if (compareMatch) {
    const [, aRaw, bRaw] = compareMatch;
    const a = visibleNodes.find((n) => n.name.toLowerCase().includes(aRaw.trim()));
    const b = visibleNodes.find((n) => n.name.toLowerCase().includes(bRaw.trim()));
    const matched = [a, b].filter((x): x is IntelNode => !!x);
    if (matched.length === 2) {
      return { matchedIds: matched.map((m) => m.id), explanation: `Comparing ${a!.name} and ${b!.name} — see their metrics in the panel on the right.` };
    }
    return { matchedIds: [], explanation: `Couldn't find both "${aRaw.trim()}" and "${bRaw.trim()}" in the current view — try expanding the graph to reveal them first.` };
  }

  const salesMatch = q.match(/(?:top|highest|most)\s+(?:sales|transactions?|activity)/);
  if (salesMatch) {
    const ranked = [...visibleNodes].sort((a, b) => (parseMetric(b, "Sales") ?? 0) - (parseMetric(a, "Sales") ?? 0)).slice(0, 3);
    return {
      matchedIds: ranked.map((m) => m.id),
      explanation: ranked.length ? `Highest sales activity in the current view: ${ranked.map((m) => m.name).join(", ")}.` : "No sales data available in the current view.",
    };
  }

  const nameMatches = visibleNodes.filter((n) => n.name.toLowerCase().includes(q) || n.subtitle?.toLowerCase().includes(q));
  if (nameMatches.length > 0) {
    return { matchedIds: nameMatches.map((m) => m.id), explanation: `Found ${nameMatches.length} match${nameMatches.length === 1 ? "" : "es"} in the current view.` };
  }

  return {
    matchedIds: [],
    explanation:
      "No matches in the current view for that query. Try \"yield > 7\", \"compare X with Y\", \"top sales\", or a specific area/project name — or expand the graph to bring more data into view. Deeper natural-language understanding will connect to the Dubai Intelligence LLM backend once available.",
  };
}
