import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Link } from "react-router-dom";
import { useFilters } from "../state/FilterContext";
import { fetchChildren, ROOT_NODE, type IntelNode } from "../lib/graph";
import { runQuery } from "../lib/queryInterpreter";
import { GraphNode, type GraphNodeData, type NodeEmphasis } from "../components/intel/GraphNode";
import { FloatingEdge } from "../components/intel/FloatingEdge";
import { IntelPanel } from "../components/intel/IntelPanel";
import { QueryBar } from "../components/intel/QueryBar";
import { EmptyState } from "../components/ui";

const nodeTypes = { intel: GraphNode };
const edgeTypes = { floating: FloatingEdge };

// ---- Display limits -------------------------------------------------
// These are UI-layer choices about how many nodes to draw AT ONCE, not
// claims about how many entities exist. Dubai's real area count (92, as
// of the current data) comes back from the API on every load via
// GraphSlice.totalAvailable — whenever the real count exceeds what's
// shown, a "+N more" node renders so the cap always reads as progressive
// disclosure, never as "this is the total".
const MAX_VISIBLE_ROOT_NODES = 10;
const MAX_VISIBLE_CHILDREN = 8;
const LOAD_MORE_BATCH = 8;

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

const CANVAS_CENTER = { x: 640, y: 380 };
const ANCESTOR_SPACING = 128;
const ANCESTOR_START_X = 90;
const CHILD_RADIUS_BASE = 230;
const CHILD_RADIUS_STEP = 26;
const CHILD_FAN_DEGREES = 108; // total angular spread children fan across, right of the focused node

function layoutRoot(focused: IntelNode, children: IntelNode[]): { id: string; x: number; y: number }[] {
  const positions = [{ id: focused.id, x: CANVAS_CENTER.x, y: CANVAS_CENTER.y }];
  const n = children.length || 1;
  const radius = Math.max(260, 34 * n);
  children.forEach((c, i) => {
    const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
    positions.push({ id: c.id, x: CANVAS_CENTER.x + Math.cos(angle) * radius, y: CANVAS_CENTER.y + Math.sin(angle) * radius });
  });
  return positions;
}

/** Dubai -> ... -> immediate parent -> FOCUSED -> children, read left to
 * right. Ancestors compress toward the left edge (small, dimmed) so the
 * full lineage stays visible without eating canvas width; children fan
 * outward from the focused node in an arc rather than a straight stack,
 * which is what actually reads as "branching from a parent" instead of a
 * column of unrelated circles. */
function layoutDrill(ancestors: IntelNode[], focused: IntelNode, children: IntelNode[]): { id: string; x: number; y: number }[] {
  const positions: { id: string; x: number; y: number }[] = [];
  ancestors.forEach((a, i) => {
    positions.push({ id: a.id, x: ANCESTOR_START_X + i * ANCESTOR_SPACING, y: CANVAS_CENTER.y });
  });
  const focusX = ANCESTOR_START_X + ancestors.length * ANCESTOR_SPACING + 130;
  positions.push({ id: focused.id, x: focusX, y: CANVAS_CENTER.y });

  const n = children.length || 1;
  const radius = CHILD_RADIUS_BASE + Math.max(0, n - 4) * CHILD_RADIUS_STEP;
  const spreadRad = (CHILD_FAN_DEGREES * Math.PI) / 180;
  children.forEach((c, i) => {
    const t = n === 1 ? 0.5 : i / (n - 1);
    const angle = -spreadRad / 2 + t * spreadRad;
    positions.push({ id: c.id, x: focusX + radius * Math.cos(angle), y: CANVAS_CENTER.y + radius * Math.sin(angle) });
  });
  return positions;
}

const EDGE_COLOR: Record<string, string> = {
  default: "var(--edge-default)",
  opportunity: "var(--good)",
  risk: "var(--bad)",
  selected: "var(--accent)",
};

function EdgeLegend() {
  const items: { color: string; label: string }[] = [
    { color: "var(--accent)", label: "Selected lineage (Dubai → focused node)" },
    { color: "var(--good)", label: "Opportunity — yield ≥ 7%" },
    { color: "var(--bad)", label: "Risk — yield < 4%" },
    { color: "var(--edge-default)", label: "No strong signal / no yield data" },
  ];
  return (
    <div className="absolute bottom-24 left-5 z-10 flex flex-col gap-1.5 bg-[var(--surface)]/85 backdrop-blur border border-[var(--border)] rounded-lg px-3 py-2.5">
      {items.map((it) => (
        <div key={it.label} className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
          <span className="w-4 h-[2px] rounded-full shrink-0" style={{ background: it.color }} />
          {it.label}
        </div>
      ))}
    </div>
  );
}

function GraphCanvas({
  path, setPath, childrenCache, setChildrenCache, setSelected, period,
}: {
  path: IntelNode[];
  setPath: (p: IntelNode[]) => void;
  childrenCache: Map<string, IntelNode[]>;
  setChildrenCache: (updater: (m: Map<string, IntelNode[]>) => Map<string, IntelNode[]>) => void;
  setSelected: (n: IntelNode | null) => void;
  period: string;
}) {
  const { fitView } = useReactFlow();
  const [loading, setLoading] = useState(false);
  const [highlighted, setHighlighted] = useState<Set<string> | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [totalAvailable, setTotalAvailable] = useState<Map<string, number>>(new Map());
  const [visibleCount, setVisibleCount] = useState<Map<string, number>>(new Map());

  const focused = path[path.length - 1];
  const ancestors = path.slice(0, -1);
  const parent = ancestors.length > 0 ? ancestors[ancestors.length - 1] : null;
  const allKids = childrenCache.get(focused.id) ?? [];
  const defaultVisible = parent ? MAX_VISIBLE_CHILDREN : MAX_VISIBLE_ROOT_NODES;
  const shown = visibleCount.get(focused.id) ?? defaultVisible;
  const kids = allKids.slice(0, shown);
  const remaining = allKids.length - kids.length;

  const loadChildren = useCallback(
    async (node: IntelNode) => {
      if (childrenCache.has(node.id)) return childrenCache.get(node.id)!;
      setLoading(true);
      try {
        const slice = await fetchChildren(node, period);
        setChildrenCache((m) => new Map(m).set(node.id, slice.nodes));
        setTotalAvailable((m) => new Map(m).set(node.id, slice.totalAvailable));
        return slice.nodes;
      } finally {
        setLoading(false);
      }
    },
    [childrenCache, setChildrenCache, period],
  );

  useEffect(() => {
    loadChildren(focused);
  }, [focused.id, period]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelect = useCallback(
    async (node: IntelNode) => {
      setSelected(node);
      setHighlighted(null);
      setExplanation(null);
      if (node.hasChildren && node.id !== focused.id) {
        await loadChildren(node);
        setPath([...path, node]);
      }
    },
    [focused.id, loadChildren, path, setPath, setSelected],
  );

  const goToAncestor = useCallback(
    (node: IntelNode) => {
      const idx = path.findIndex((p) => p.id === node.id);
      if (idx === -1) return;
      const nextPath = path.slice(0, idx + 1);
      setPath(nextPath);
      setSelected(nextPath[nextPath.length - 1]);
      setHighlighted(null);
      setExplanation(null);
    },
    [path, setPath, setSelected],
  );

  const goBack = useCallback(() => {
    if (path.length <= 1) return;
    goToAncestor(path[path.length - 2]);
  }, [path, goToAncestor]);

  const showMore = useCallback(() => {
    setVisibleCount((m) => new Map(m).set(focused.id, shown + LOAD_MORE_BATCH));
  }, [focused.id, shown]);

  useEffect(() => {
    const t = setTimeout(() => fitView({ padding: 0.24, duration: 500 }), 40);
    return () => clearTimeout(t);
  }, [focused.id, kids.length, ancestors.length, fitView]);

  // The "+N more" node is laid out as one more slot in the SAME fan/ring as
  // the real children (computed together, in one pass) — laying it out
  // separately would use a different spacing (N vs N+1 items) and land it
  // on top of a real sibling, which is exactly the overlap bug this avoids.
  const moreNode: IntelNode | null = useMemo(() => {
    if (remaining <= 0) return null;
    return {
      id: `more:${focused.id}`, type: allKids[0]?.type ?? "area", name: `+${remaining} more`, shortCode: "",
      metrics: [], parentId: focused.id, hasChildren: false, fetchKey: "", raw: { remaining },
    };
  }, [remaining, focused.id, allKids]);

  const displayChildren = useMemo(() => (moreNode ? [...kids, moreNode] : kids), [kids, moreNode]);

  const positions = useMemo(
    () => (parent ? layoutDrill(ancestors, focused, displayChildren) : layoutRoot(focused, displayChildren)),
    [parent, ancestors, focused, displayChildren],
  );
  const posMap = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);

  const nodes: Node[] = useMemo(() => {
    const list: Node[] = [];
    ancestors.forEach((a, i) => {
      const p = posMap.get(a.id);
      if (!p) return;
      const isImmediateParent = i === ancestors.length - 1;
      list.push({
        id: a.id, type: "intel", position: { x: p.x, y: p.y }, draggable: false, selectable: false,
        data: {
          node: a,
          emphasis: (highlighted && !highlighted.has(a.id) ? "dimmed" : isImmediateParent ? "parent" : "trail") as NodeEmphasis,
          onSelect: () => goToAncestor(a),
        } satisfies GraphNodeData,
      });
    });
    const f = posMap.get(focused.id);
    if (f) {
      list.push({
        id: focused.id, type: "intel", position: { x: f.x, y: f.y }, draggable: false, selectable: false,
        data: { node: focused, emphasis: (highlighted && !highlighted.has(focused.id) ? "dimmed" : "focused") as NodeEmphasis, onSelect: () => setSelected(focused) } satisfies GraphNodeData,
      });
    }
    kids.forEach((c) => {
      const cp = posMap.get(c.id);
      if (!cp) return;
      list.push({
        id: c.id, type: "intel", position: { x: cp.x, y: cp.y }, draggable: false, selectable: false,
        data: { node: c, emphasis: (highlighted && !highlighted.has(c.id) ? "dimmed" : "child") as NodeEmphasis, onSelect: handleSelect } satisfies GraphNodeData,
      });
    });
    if (moreNode) {
      const mp = posMap.get(moreNode.id);
      if (mp) {
        list.push({
          id: moreNode.id, type: "intel", position: { x: mp.x, y: mp.y }, draggable: false, selectable: false,
          data: { node: moreNode, emphasis: "more" as NodeEmphasis, onSelect: showMore } satisfies GraphNodeData,
        });
      }
    }
    return list;
  }, [ancestors, focused, kids, posMap, handleSelect, goToAncestor, setSelected, highlighted, moreNode, showMore]);

  const edges: Edge[] = useMemo(() => {
    const list: Edge[] = [];
    for (let i = 0; i < ancestors.length; i++) {
      const a = ancestors[i];
      const b = i + 1 < ancestors.length ? ancestors[i + 1] : focused;
      list.push({
        id: `e:${a.id}->${b.id}`, source: a.id, target: b.id, type: "floating",
        style: { stroke: EDGE_COLOR.selected, strokeWidth: 2 },
        markerEnd: i === ancestors.length - 1 ? { type: MarkerType.ArrowClosed, color: EDGE_COLOR.selected, width: 14, height: 14 } : undefined,
      });
    }
    kids.forEach((c) => {
      const isHighlighted = !highlighted || highlighted.has(c.id);
      const category = c.metrics.find((m) => m.label === "Est. Yield")?.tone === "good" ? "opportunity" : c.metrics.find((m) => m.label === "Est. Yield")?.tone === "bad" ? "risk" : "default";
      list.push({
        id: `e:${focused.id}->${c.id}`, source: focused.id, target: c.id, type: "floating",
        style: { stroke: EDGE_COLOR[category], strokeWidth: category === "default" ? 1.2 : 1.8, opacity: isHighlighted ? (category === "default" ? 0.45 : 0.85) : 0.12 },
        animated: category !== "default" && isHighlighted,
      });
    });
    if (moreNode) {
      list.push({
        id: `e:${focused.id}->more`, source: focused.id, target: moreNode.id, type: "floating",
        style: { stroke: "var(--edge-default)", strokeWidth: 1, strokeDasharray: "3 3", opacity: 0.7 },
      });
    }
    return list;
  }, [ancestors, focused, kids, highlighted, moreNode]);

  const visibleNodes = useMemo(() => [...ancestors, focused, ...kids], [ancestors, focused, kids]);

  const handleQuery = (q: string) => {
    const result = runQuery(q, visibleNodes);
    setHighlighted(result.matchedIds.length ? new Set(result.matchedIds) : null);
    setExplanation(result.explanation);
  };

  return (
    <div className="relative flex-1 h-full">
      <div className="absolute top-4 left-5 z-10 flex items-center gap-1.5 text-xs flex-wrap max-w-[70%]">
        <Link to="/" className="text-[var(--text-muted)] hover:text-[var(--text)]">Dubai</Link>
        {path.slice(1).map((n, i) => (
          <span key={n.id} className="flex items-center gap-1.5">
            <span className="text-[var(--text-muted)]">/</span>
            <button
              onClick={() => goToAncestor(n)}
              className={i === path.length - 2 ? "text-[var(--accent)] font-medium" : "text-[var(--text-muted)] hover:text-[var(--text)]"}
            >
              {n.name}
            </button>
          </span>
        ))}
        {loading && <span className="text-[var(--text-muted)] ml-2 animate-pulse">loading…</span>}
        {!loading && totalAvailable.has(focused.id) && kids.length < totalAvailable.get(focused.id)! && (
          <span className="text-[var(--text-muted)] ml-2">
            — showing {kids.length} of {totalAvailable.get(focused.id)} by activity
          </span>
        )}
      </div>

      {path.length > 1 && (
        <button
          onClick={goBack}
          className="absolute top-4 right-5 z-10 text-xs text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded-full px-3 py-1.5 bg-[var(--surface)]/80 backdrop-blur"
        >
          &larr; Back
        </button>
      )}

      {!loading && allKids.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="pointer-events-auto">
            <EmptyState title="No connected entities available" detail={`${focused.name} has no further drill-down data in the current dataset.`} />
          </div>
        </div>
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={(_event, flowNode) => {
          const d = flowNode.data as GraphNodeData;
          d.onSelect(d.node);
        }}
        fitView
        minZoom={0.3}
        maxZoom={1.5}
        panOnScroll
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="var(--border)" style={{ opacity: 0.5 }} />
        <Controls showInteractive={false} className="!bg-[var(--surface)] !border !border-[var(--border)] !shadow-lg [&>button]:!bg-[var(--surface)] [&>button]:!border-[var(--border)] [&>button]:!text-[var(--text)] [&>button:hover]:!bg-[var(--hover-overlay)]" />
      </ReactFlow>

      <EdgeLegend />
      <QueryBar onQuery={handleQuery} explanation={explanation} />
    </div>
  );
}

export function IntelligenceMap() {
  const { period } = useFilters();
  const [path, setPath] = useState<IntelNode[]>([ROOT_NODE]);
  const [childrenCache, setChildrenCache] = useState<Map<string, IntelNode[]>>(new Map());
  const [selected, setSelected] = useState<IntelNode | null>(ROOT_NODE);

  // A period change invalidates cached metrics — reset to Dubai to avoid
  // showing stale-period numbers under a fresh path.
  useEffect(() => {
    setPath([ROOT_NODE]);
    setSelected(ROOT_NODE);
    setChildrenCache(new Map());
  }, [period]);

  const focused = path[path.length - 1];
  const kids = childrenCache.get(focused.id) ?? [];

  return (
    <div className="intel-scope flex h-full w-full -m-6" style={{ height: "calc(100% + 3rem)", transition: `background-color 400ms ${cubicBezierCss(EASE)}` }}>
      <ReactFlowProvider>
        <GraphCanvas
          path={path} setPath={setPath}
          childrenCache={childrenCache} setChildrenCache={setChildrenCache}
          setSelected={setSelected}
          period={period}
        />
      </ReactFlowProvider>
      <div className="w-[340px] shrink-0">
        {childrenCache.has(focused.id) ? (
          <IntelPanel node={selected ?? focused} children={kids} />
        ) : (
          <div className="h-full border-l border-[var(--border)] p-5 space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-14 rounded-lg bg-[var(--surface-2)] animate-pulse" style={{ animationDelay: `${i * 80}ms` }} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function cubicBezierCss([a, b, c, d]: [number, number, number, number]): string {
  return `cubic-bezier(${a}, ${b}, ${c}, ${d})`;
}
