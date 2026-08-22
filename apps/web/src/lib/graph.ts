/**
 * Intelligence Graph adapter — translates existing API responses (areas,
 * projects, developers) into a normalized node/edge model for the graph
 * visualization. This is purely a frontend view layer: no backend contract
 * changes beyond one additive endpoint (GET /api/areas/{id}/projects).
 *
 * Nothing here fabricates data. Every metric traces back to a real field on
 * a real API response; a metric that isn't available renders as `null` and
 * the UI shows "Data unavailable" rather than inventing a value.
 */
import { api, type AreaChildItem, type AreaListItem, type AreaProjectItem, type MasterProjectDetail } from "./api";
import { formatAed, formatNumber, formatPct, formatPsf } from "./format";

export type GraphNodeType = "market" | "area" | "project" | "building" | "unitType" | "developer";

export interface GraphMetric {
  label: string;
  value: string;
  tone?: "good" | "bad" | "warn" | "neutral";
}

export interface IntelNode {
  id: string;
  type: GraphNodeType;
  name: string;
  subtitle?: string;
  badge?: string;
  metrics: GraphMetric[];
  parentId: string | null;
  hasChildren: boolean;
  fetchKey: string; // opaque key passed back to fetchChildren to load this node's children
  raw: unknown;
}

export type EdgeCategory = "default" | "important" | "opportunity" | "risk";

export interface IntelEdge {
  id: string;
  source: string;
  target: string;
  category: EdgeCategory;
}

export interface GraphSlice {
  nodes: IntelNode[];
  edges: IntelEdge[];
}

const DUBAI_ID = "market:dubai";

export const ROOT_NODE: IntelNode = {
  id: DUBAI_ID,
  type: "market",
  name: "DUBAI",
  subtitle: "Residential Market",
  metrics: [],
  parentId: null,
  hasChildren: true,
  fetchKey: "root",
  raw: null,
};

function yieldTone(pct: number | null): GraphMetric["tone"] {
  if (pct === null) return "neutral";
  if (pct >= 7) return "good";
  if (pct < 4) return "bad";
  return "neutral";
}

function areaNode(a: AreaListItem | AreaChildItem, parentId: string): IntelNode {
  const yieldPct = a.estimated_gross_yield_pct;
  const salesCount = "sales_count" in a ? a.sales_count : 0;
  const rentalCount = "rental_count" in a ? a.rental_count : 0;
  const childCount = "child_count" in a ? a.child_count : 0;
  return {
    id: `area:${a.area_id}`,
    type: "area",
    name: a.name.toUpperCase(),
    subtitle: "Area",
    badge: yieldPct !== null ? `Yield ${yieldPct.toFixed(1)}%` : undefined,
    metrics: [
      { label: "Sales", value: formatNumber(salesCount) },
      { label: "Rentals", value: formatNumber(rentalCount) },
      { label: "Median Price", value: formatAed(a.median_price) },
      { label: "Est. Yield", value: yieldPct !== null ? formatPct(yieldPct) : "Data unavailable", tone: yieldTone(yieldPct) },
    ],
    parentId,
    hasChildren: childCount > 0 || true, // areas may also reveal matched projects even with no sub-areas
    fetchKey: `area:${a.area_id}`,
    raw: a,
  };
}

function projectNode(p: AreaProjectItem, parentId: string): IntelNode {
  return {
    id: `project:${p.slug}`,
    type: "project",
    name: p.name.trim().toUpperCase(),
    subtitle: p.developer_name ?? "Project",
    badge: p.median_psf !== null ? `${formatPsf(p.median_psf)}` : undefined,
    metrics: [
      { label: "Buildings", value: formatNumber(p.building_count) },
      { label: "Sales", value: formatNumber(p.sales_count) },
      { label: "Median Price", value: formatAed(p.median_price) },
      {
        label: "Est. Yield",
        value: p.estimated_gross_yield_pct !== null ? formatPct(p.estimated_gross_yield_pct) : "Data unavailable",
        tone: yieldTone(p.estimated_gross_yield_pct),
      },
    ],
    parentId,
    hasChildren: p.building_count > 0,
    fetchKey: `project:${p.slug}`,
    raw: p,
  };
}

function developerNode(name: string, parentId: string): IntelNode {
  return {
    id: `developer:${parentId}:${name}`,
    type: "developer",
    name: name.toUpperCase(),
    subtitle: "Developer",
    metrics: [],
    parentId,
    hasChildren: false,
    fetchKey: "",
    raw: { name },
  };
}

function buildingNode(b: MasterProjectDetail["buildings"][number], perf: MasterProjectDetail["building_performance"][number] | undefined, masterSlug: string, parentId: string): IntelNode {
  return {
    id: `building:${b.slug}`,
    type: "building",
    name: (b.building_label ?? b.name).toUpperCase(),
    subtitle: "Building",
    badge: perf?.avg_psf !== undefined && perf.avg_psf !== null ? formatPsf(perf.avg_psf) : undefined,
    metrics: [
      { label: "Sales", value: formatNumber(perf?.sales_count ?? 0) },
      { label: "Avg Price", value: formatAed(perf?.avg_price ?? null) },
      { label: "Rentals", value: formatNumber(perf?.rental_count ?? 0) },
      {
        label: "Est. Yield",
        value: perf?.estimated_gross_yield_pct != null ? formatPct(perf.estimated_gross_yield_pct) : "Data unavailable",
        tone: yieldTone(perf?.estimated_gross_yield_pct ?? null),
      },
    ],
    parentId,
    hasChildren: true,
    fetchKey: `building:${masterSlug}:${b.slug}`,
    raw: { building: b, performance: perf },
  };
}

function unitTypeNode(u: MasterProjectDetail["unit_type_performance"][number], parentId: string): IntelNode {
  return {
    id: `unittype:${parentId}:${u.bedroom}`,
    type: "unitType",
    name: u.bedroom.toUpperCase(),
    subtitle: "Unit Type",
    badge: u.avg_psf !== null ? formatPsf(u.avg_psf) : undefined,
    metrics: [
      { label: "Sales", value: formatNumber(u.sales_count) },
      { label: "Avg Price", value: formatAed(u.avg_price) },
      { label: "Avg Rent", value: formatAed(u.avg_rent) },
      {
        label: "Est. Yield",
        value: u.estimated_gross_yield_pct !== null ? formatPct(u.estimated_gross_yield_pct) : "Data unavailable",
        tone: yieldTone(u.estimated_gross_yield_pct),
      },
    ],
    parentId,
    hasChildren: false,
    fetchKey: "",
    raw: u,
  };
}

function edgesFor(parentId: string, nodes: IntelNode[], period: string): IntelEdge[] {
  return nodes.map((n) => {
    let category: EdgeCategory = "default";
    const yieldMetric = n.metrics.find((m) => m.label === "Est. Yield");
    if (yieldMetric?.tone === "good") category = "opportunity";
    else if (yieldMetric?.tone === "bad") category = "risk";
    return { id: `edge:${parentId}->${n.id}:${period}`, source: parentId, target: n.id, category };
  });
}

/** Fetches the next level of the graph below `node`. Called on expand. */
export async function fetchChildren(node: IntelNode, period: string): Promise<GraphSlice> {
  if (node.fetchKey === "root") {
    const res = await api.areas(period);
    const top = [...res.items].sort((a, b) => b.sales_count + b.rental_count - (a.sales_count + a.rental_count)).slice(0, 10);
    const nodes = top.map((a) => areaNode(a, node.id));
    return { nodes, edges: edgesFor(node.id, nodes, period) };
  }

  if (node.fetchKey.startsWith("area:")) {
    const areaId = node.fetchKey.split(":")[1];
    const [detail, projects] = await Promise.all([
      api.areaDetail(areaId, period),
      api.areaProjects(areaId, period, 8).catch(() => ({ period, items: [] as AreaProjectItem[] })),
    ]);
    const subAreas = [...detail.children]
      .sort((a, b) => b.sales_count + b.rental_count + b.project_matched_stats.sales_count - (a.sales_count + a.rental_count + a.project_matched_stats.sales_count))
      .slice(0, 5)
      .map((c) => areaNode(c, node.id));
    const projectNodes = projects.items.slice(0, 5).map((p) => projectNode(p, node.id));
    const nodes = [...subAreas, ...projectNodes];
    return { nodes, edges: edgesFor(node.id, nodes, period) };
  }

  if (node.fetchKey.startsWith("project:")) {
    const slug = node.fetchKey.split(":")[1];
    const detail = await api.masterProjectDetail(slug, period);
    const perfBySlug = new Map(detail.building_performance.map((p) => [p.slug, p]));
    const buildingNodes = detail.buildings.map((b) => buildingNode(b, perfBySlug.get(b.slug), slug, node.id));
    const devNodes = detail.developer_name ? [developerNode(detail.developer_name, node.id)] : [];
    const nodes = [...buildingNodes, ...devNodes];
    return { nodes, edges: edgesFor(node.id, nodes, period) };
  }

  if (node.fetchKey.startsWith("building:")) {
    const [, masterSlug, buildingSlug] = node.fetchKey.split(":");
    const detail = await api.masterProjectDetail(masterSlug, period, buildingSlug);
    const nodes = detail.unit_type_performance.filter((u) => u.sales_count > 0 || u.rental_count > 0).map((u) => unitTypeNode(u, node.id));
    return { nodes, edges: edgesFor(node.id, nodes, period) };
  }

  return { nodes: [], edges: [] };
}
