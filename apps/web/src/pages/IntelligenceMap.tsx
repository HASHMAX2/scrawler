import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { IntelPanel } from "../components/intel/IntelPanel";
import { QueryBar } from "../components/intel/QueryBar";
import { LoadingSkeleton } from "../components/ui";

const nodeTypes = { intel: GraphNode };

const CANVAS_CENTER = { x: 620, y: 360 };
const ROOT_RADIUS = 300;
const DRILL_PARENT_X = 140;
const DRILL_FOCUS_X = 520;
const DRILL_CHILD_X = 960;
const CHILD_SPACING = 118;
const CHILD_X_JITTER = 70;

function layout(path: IntelNode[], children: IntelNode[]): { id: string; x: number; y: number }[] {
  const focused = path[path.length - 1];
  const parent = path.length > 1 ? path[path.length - 2] : null;

  if (!parent) {
    const positions = [{ id: focused.id, x: CANVAS_CENTER.x, y: CANVAS_CENTER.y }];
    const n = children.length || 1;
    children.forEach((c, i) => {
      const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
      positions.push({ id: c.id, x: CANVAS_CENTER.x + Math.cos(angle) * ROOT_RADIUS, y: CANVAS_CENTER.y + Math.sin(angle) * ROOT_RADIUS });
    });
    return positions;
  }

  const positions = [
    { id: parent.id, x: DRILL_PARENT_X, y: CANVAS_CENTER.y },
    { id: focused.id, x: DRILL_FOCUS_X, y: CANVAS_CENTER.y },
  ];
  const n = children.length;
  children.forEach((c, i) => {
    const offset = i - (n - 1) / 2;
    positions.push({ id: c.id, x: DRILL_CHILD_X + Math.abs(offset % 2) * CHILD_X_JITTER, y: CANVAS_CENTER.y + offset * CHILD_SPACING });
  });
  return positions;
}

const EDGE_COLOR: Record<string, string> = {
  default: "var(--text-muted)",
  important: "var(--accent)",
  opportunity: "var(--good)",
  risk: "var(--bad)",
  selected: "var(--accent)",
};

// Connections are colored by the child's estimated gross yield: green when
// it clears 7%, coral when it's under 4%, neutral otherwise — the same
// signal shown as a metric tone in the right panel and the query bar's
// "yield > 7" filter. Nodes with no calculable yield (no matched
// transactions) get the neutral color, which is why some lines look
// "unstyled" — that's an honest reflection of missing data, not a bug.
function EdgeLegend() {
  const items: { color: string; label: string }[] = [
    { color: "var(--accent)", label: "Path to focused node" },
    { color: "var(--good)", label: "Opportunity — yield ≥ 7%" },
    { color: "var(--bad)", label: "Risk — yield < 4%" },
    { color: "var(--border)", label: "No strong signal / no yield data" },
  ];
  return (
    <div className="absolute bottom-24 left-5 z-10 flex flex-col gap-1.5 bg-[var(--surface)]/80 backdrop-blur border border-[var(--border)] rounded-lg px-3 py-2.5">
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

  const focused = path[path.length - 1];
  const parent = path.length > 1 ? path[path.length - 2] : null;
  const kids = childrenCache.get(focused.id) ?? [];

  const loadChildren = useCallback(
    async (node: IntelNode) => {
      if (childrenCache.has(node.id)) return childrenCache.get(node.id)!;
      setLoading(true);
      try {
        const slice = await fetchChildren(node, period);
        setChildrenCache((m) => new Map(m).set(node.id, slice.nodes));
        if (slice.totalAvailable !== undefined) {
          setTotalAvailable((m) => new Map(m).set(node.id, slice.totalAvailable!));
        }
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

  const goBack = useCallback(() => {
    if (path.length <= 1) return;
    const nextPath = path.slice(0, -1);
    setPath(nextPath);
    setSelected(nextPath[nextPath.length - 1]);
    setHighlighted(null);
    setExplanation(null);
  }, [path, setPath, setSelected]);

  useEffect(() => {
    const t = setTimeout(() => fitView({ padding: 0.28, duration: 650 }), 60);
    return () => clearTimeout(t);
  }, [focused.id, kids.length, fitView]);

  const positions = useMemo(() => layout(path, kids), [path, kids]);
  const posMap = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);

  const nodes: Node[] = useMemo(() => {
    const list: Node[] = [];
    if (parent) {
      const p = posMap.get(parent.id)!;
      list.push({
        id: parent.id, type: "intel", position: { x: p.x, y: p.y }, draggable: false, selectable: false,
        data: { node: parent, emphasis: (highlighted && !highlighted.has(parent.id) ? "dimmed" : "parent") as NodeEmphasis, onSelect: goBack } satisfies GraphNodeData,
      });
    }
    const f = posMap.get(focused.id)!;
    list.push({
      id: focused.id, type: "intel", position: { x: f.x, y: f.y }, draggable: false, selectable: false,
      data: { node: focused, emphasis: (highlighted && !highlighted.has(focused.id) ? "dimmed" : "focused") as NodeEmphasis, onSelect: () => setSelected(focused) } satisfies GraphNodeData,
    });
    kids.forEach((c) => {
      const cp = posMap.get(c.id)!;
      list.push({
        id: c.id, type: "intel", position: { x: cp.x, y: cp.y }, draggable: false, selectable: false,
        data: { node: c, emphasis: (highlighted && !highlighted.has(c.id) ? "dimmed" : "child") as NodeEmphasis, onSelect: handleSelect } satisfies GraphNodeData,
      });
    });
    return list;
  }, [parent, focused, kids, posMap, handleSelect, goBack, setSelected, highlighted]);

  const edges: Edge[] = useMemo(() => {
    const list: Edge[] = [];
    if (parent) {
      list.push({
        id: `e:${parent.id}->${focused.id}`, source: parent.id, target: focused.id, type: "straight",
        style: { stroke: EDGE_COLOR.selected, strokeWidth: 2 }, animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLOR.selected, width: 14, height: 14 },
      });
    }
    kids.forEach((c) => {
      const isHighlighted = !highlighted || highlighted.has(c.id);
      const category = c.metrics.find((m) => m.label === "Est. Yield")?.tone === "good" ? "opportunity" : c.metrics.find((m) => m.label === "Est. Yield")?.tone === "bad" ? "risk" : "default";
      list.push({
        id: `e:${focused.id}->${c.id}`, source: focused.id, target: c.id, type: "straight",
        style: { stroke: EDGE_COLOR[category], strokeWidth: category === "default" ? 1.2 : 1.8, opacity: isHighlighted ? (category === "default" ? 0.4 : 0.8) : 0.12 },
        animated: category !== "default" && isHighlighted,
      });
    });
    return list;
  }, [parent, focused, kids, highlighted]);

  const visibleNodes = useMemo(() => [parent, focused, ...kids].filter((n): n is IntelNode => !!n), [parent, focused, kids]);

  const handleQuery = (q: string) => {
    const result = runQuery(q, visibleNodes);
    setHighlighted(result.matchedIds.length ? new Set(result.matchedIds) : null);
    setExplanation(result.explanation);
  };

  return (
    <div className="relative flex-1 h-full">
      <div className="absolute top-4 left-5 z-10 flex items-center gap-1.5 text-xs">
        <Link to="/" className="text-[var(--text-muted)] hover:text-[var(--text)]">Dubai</Link>
        {path.slice(1).map((n, i) => (
          <span key={n.id} className="flex items-center gap-1.5">
            <span className="text-[var(--text-muted)]">/</span>
            <button
              onClick={() => {
                setPath(path.slice(0, i + 2));
                setSelected(n);
              }}
              className={i === path.length - 2 ? "text-[var(--accent)] font-medium" : "text-[var(--text-muted)] hover:text-[var(--text)]"}
            >
              {n.name}
            </button>
          </span>
        ))}
        {loading && <span className="text-[var(--text-muted)] ml-2 animate-pulse">loading…</span>}
        {!loading && totalAvailable.has(focused.id) && kids.length < totalAvailable.get(focused.id)! && (
          <span className="text-[var(--text-muted)] ml-2">
            — showing top {kids.length} of {totalAvailable.get(focused.id)} by activity
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

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_event, flowNode) => {
          const d = flowNode.data as GraphNodeData;
          d.onSelect(d.node);
        }}
        fitView
        minZoom={0.35}
        maxZoom={1.4}
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
  const cacheRef = useRef(childrenCache);
  cacheRef.current = childrenCache;

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
    <div className="intel-scope flex h-full w-full -m-6" style={{ height: "calc(100% + 3rem)" }}>
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
          <div className="h-full border-l border-[var(--border)] p-5">
            <LoadingSkeleton rows={4} />
          </div>
        )}
      </div>
    </div>
  );
}
