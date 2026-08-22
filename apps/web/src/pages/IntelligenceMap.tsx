import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods, type NodeObject } from "react-force-graph-3d";
import { forceCollide } from "d3-force-3d";
import * as THREE from "three";
import SpriteText from "three-spritetext";
import { Link } from "react-router-dom";
import { useFilters } from "../state/FilterContext";
import { useTheme } from "../state/ThemeContext";
import { fetchChildren, ROOT_NODE, type EdgeCategory, type IntelNode } from "../lib/graph";
import { intelColors, type IntelColorSet } from "../lib/intelColors";
import { runQuery } from "../lib/queryInterpreter";
import { useElementSize } from "../lib/useElementSize";
import { IntelPanel } from "../components/intel/IntelPanel";
import { QueryBar } from "../components/intel/QueryBar";

type GNode = IntelNode & { x?: number; y?: number; z?: number };
type GLink = { id: string; source: string; target: string; category: EdgeCategory };

/** Sphere radius by tier — root is clearly the largest, area/community
 * nodes are mid-sized ("primary entities"), everything below (project,
 * building, developer, unit type) is the smallest tier. No emphasis-based
 * resizing here on top of this — focus/selection is communicated by a
 * halo ring and opacity instead (see updateNodeAppearance), so a node's
 * base size never changes and the layout stays predictable. */
function radiusFor(node: GNode): number {
  if (node.type === "market") return 26;
  if (node.type === "area") return 15;
  return 9;
}

function categoryColor(category: EdgeCategory, colors: IntelColorSet): string {
  if (category === "opportunity") return colors.good;
  if (category === "risk") return colors.bad;
  return colors.edgeDefault;
}

function buildNodeObject(node: GNode, colors: IntelColorSet): THREE.Group {
  const group = new THREE.Group();
  const color = colors.node[node.type];
  const r = radiusFor(node);

  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(r, 24, 24),
    new THREE.MeshPhongMaterial({ color, shininess: 65, transparent: true, opacity: 0.85 }),
  );
  group.add(sphere);

  // Halo ring — hidden by default (opacity 0), toggled visible for the
  // focused node and the selected lineage by updateNodeAppearance below.
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(r * 1.35, r * 1.5, 40),
    new THREE.MeshBasicMaterial({ color: colors.accent, transparent: true, opacity: 0, side: THREE.DoubleSide }),
  );
  group.add(ring);

  const label = new SpriteText(node.name);
  label.color = colors.text;
  label.textHeight = node.type === "market" ? 5.4 : node.type === "area" ? 3.6 : 2.8;
  label.position.set(0, r + 5, 0);
  group.add(label);

  if (node.badge) {
    const badge = new SpriteText(node.badge);
    badge.color = color;
    badge.textHeight = 2.3;
    badge.position.set(0, r + 5 - (node.type === "market" ? 6.6 : 4.6), 0);
    group.add(badge);
  }

  group.userData.sphere = sphere;
  group.userData.ring = ring;
  return group;
}

export function IntelligenceMap() {
  const { period } = useFilters();
  const { theme } = useTheme();
  const colors = useMemo(() => intelColors(theme), [theme]);

  const fgRef = useRef<ForceGraphMethods<GNode, GLink> | undefined>(undefined);
  const objectsRef = useRef<Map<string, THREE.Group>>(new Map());
  const hasFitRef = useRef(false);
  const { ref: containerRef, size } = useElementSize<HTMLDivElement>();

  const [nodesMap, setNodesMap] = useState<Map<string, GNode>>(new Map());
  const [edgesMap, setEdgesMap] = useState<Map<string, GLink>>(new Map());
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [focusedId, setFocusedId] = useState<string>(ROOT_NODE.id);
  const [selected, setSelected] = useState<IntelNode | null>(ROOT_NODE);
  const [loading, setLoading] = useState(true);
  const [highlighted, setHighlighted] = useState<Set<string> | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);

  // Fresh graph on mount and whenever the period changes (cached metrics
  // are period-scoped, so a period switch resets back to Dubai).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    hasFitRef.current = false;
    objectsRef.current.clear();
    (async () => {
      const slice = await fetchChildren(ROOT_NODE, period);
      if (cancelled) return;
      const nmap = new Map<string, GNode>([[ROOT_NODE.id, { ...ROOT_NODE }]]);
      slice.nodes.forEach((n) => nmap.set(n.id, { ...n }));
      const emap = new Map<string, GLink>();
      slice.edges.forEach((e) => emap.set(e.id, e));
      setNodesMap(nmap);
      setEdgesMap(emap);
      setExpandedIds(new Set([ROOT_NODE.id]));
      setFocusedId(ROOT_NODE.id);
      setSelected(ROOT_NODE);
      setHighlighted(null);
      setExplanation(null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [period]);

  const mergeChildren = useCallback((newNodes: IntelNode[], newEdges: { id: string; source: string; target: string; category: EdgeCategory }[]) => {
    setNodesMap((prev) => {
      const next = new Map(prev);
      let changed = false;
      newNodes.forEach((n) => {
        if (!next.has(n.id)) {
          next.set(n.id, { ...n });
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    setEdgesMap((prev) => {
      const next = new Map(prev);
      let changed = false;
      newEdges.forEach((e) => {
        if (!next.has(e.id)) {
          next.set(e.id, e);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, []);

  // Drilling into a node with children frames the camera around that node
  // PLUS its children (via zoomToFit's nodeFilter) rather than flying to a
  // fixed distance from the clicked node alone — the fixed-distance version
  // left the other ~90 unrelated siblings from the previous view rendered
  // at their old (now visually irrelevant) scale, which is exactly what
  // made drill-down feel cluttered with labels stacking behind nodes. A
  // short delay lets the just-reheated force simulation spread the new
  // children away from the parent's initial (stacked) spawn position
  // before the camera fits to their bounding box. Leaf nodes (no children)
  // have nothing to fit around, so they keep the simple fly-to-node framing.
  const focusCamera = useCallback((id: string, node: GNode, willHaveChildren: boolean) => {
    if (willHaveChildren) {
      window.setTimeout(() => {
        fgRef.current?.zoomToFit(800, 90, (n) => n.id === id || (n as GNode).parentId === id);
      }, 450);
      return;
    }
    const distance = 110;
    const { x = 0, y = 0, z = 0 } = node;
    const dist = Math.hypot(x, y, z) || 1;
    const ratio = 1 + distance / dist;
    fgRef.current?.cameraPosition({ x: x * ratio, y: y * ratio, z: z * ratio }, { x, y, z }, 900);
  }, []);

  // Shared by clicking a node in the 3D scene AND clicking a row in the
  // alphabetical area / sub-community list panels — both are just "the user
  // picked this entity," so both should expand/focus/fly the same way.
  const selectNode = useCallback(
    async (node: GNode) => {
      const id = String(node.id);
      setSelected(node);
      setFocusedId(id);
      setHighlighted(null);
      setExplanation(null);

      let willHaveChildren = node.hasChildren && expandedIds.has(id);
      if (node.hasChildren && !expandedIds.has(id)) {
        setLoading(true);
        try {
          const slice = await fetchChildren(node, period);
          mergeChildren(slice.nodes, slice.edges);
          setExpandedIds((prev) => new Set(prev).add(id));
          willHaveChildren = slice.nodes.length > 0;
        } finally {
          setLoading(false);
        }
      }

      focusCamera(id, node, willHaveChildren);
    },
    [expandedIds, period, mergeChildren, focusCamera],
  );

  const handleNodeClick = useCallback((node: NodeObject<GNode>) => selectNode(node), [selectNode]);

  const handleListSelect = useCallback(
    (id: string) => {
      const node = nodesMap.get(id);
      if (node) selectNode(node);
    },
    [nodesMap, selectNode],
  );

  // Breadcrumb: walk parentId back from the focused node — no separate
  // path stack needed, every node already knows its real parent.
  const breadcrumbPath = useMemo(() => {
    const trail: GNode[] = [];
    let cur = nodesMap.get(focusedId);
    const seen = new Set<string>();
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id);
      trail.unshift(cur);
      cur = cur.parentId ? nodesMap.get(cur.parentId) : undefined;
    }
    return trail;
  }, [focusedId, nodesMap]);

  const pathEdgeIds = useMemo(() => {
    const ids = new Set<string>();
    for (let i = 0; i < breadcrumbPath.length - 1; i++) {
      const a = breadcrumbPath[i].id;
      const b = breadcrumbPath[i + 1].id;
      edgesMap.forEach((e) => {
        if (e.source === a && e.target === b) ids.add(e.id);
      });
    }
    return ids;
  }, [breadcrumbPath, edgesMap]);

  const pathNodeIds = useMemo(() => new Set(breadcrumbPath.map((n) => n.id)), [breadcrumbPath]);

  // The "active neighborhood" for the current drill level: the breadcrumb
  // ancestors, the focused node itself, and its direct children. Once the
  // user has drilled past the root, everything outside this set is a
  // leftover from a previous, now-irrelevant view — dimming it (both the
  // sphere and its edges, below) is what actually fixes the "cluttered,
  // labels stack on top of each other" complaint, rather than just making
  // nodes bigger or smaller. At the root, null means "show everything":
  // that full 92-area view is the intended top-level picture, not clutter.
  const activeIds = useMemo(() => {
    if (focusedId === ROOT_NODE.id) return null;
    const ids = new Set(pathNodeIds);
    nodesMap.forEach((n) => {
      if (n.parentId === focusedId) ids.add(n.id);
    });
    return ids;
  }, [focusedId, pathNodeIds, nodesMap]);

  // Directly mutate the cached Three.js objects rather than rebuilding the
  // whole scene — cheap, and avoids resetting the physics-simulated x/y/z
  // any rebuild would otherwise risk disturbing.
  useEffect(() => {
    objectsRef.current.forEach((group, id) => {
      const isFocused = id === focusedId;
      const onPath = pathNodeIds.has(id);
      const inNeighborhood = !activeIds || activeIds.has(id);
      const isQueryMatch = !highlighted || highlighted.has(id);
      const ring = group.userData.ring as THREE.Mesh;
      const sphere = group.userData.sphere as THREE.Mesh;
      const ringMat = ring.material as THREE.MeshBasicMaterial;
      const sphereMat = sphere.material as THREE.MeshPhongMaterial;
      ringMat.opacity = isFocused ? 0.85 : 0;
      sphereMat.opacity = !isQueryMatch ? 0.12 : !inNeighborhood ? 0.1 : isFocused || onPath ? 0.95 : 0.75;
      group.scale.setScalar(isFocused ? 1.3 : 1);
    });
  }, [focusedId, pathNodeIds, activeIds, highlighted]);

  const nodeThreeObject = useCallback(
    (node: NodeObject<GNode>) => {
      const group = buildNodeObject(node, colors);
      objectsRef.current.set(String(node.id), group);
      return group;
    },
    [colors],
  );

  const graphData = useMemo(
    () => ({
      nodes: Array.from(nodesMap.values()),
      links: Array.from(edgesMap.values()).map((e) => ({ ...e })),
    }),
    [nodesMap, edgesMap],
  );

  // Default 3d-force-graph physics (charge -30, link distance 30) is tuned
  // for small graphs and leaves ~90 sibling nodes clumped in a tight,
  // overlapping ball with unreadable labels. Scale repulsion/link distance
  // to the node's own radius (+ label headroom) and add an explicit
  // collision force so spheres and their labels never overlap, however many
  // real siblings a level has.
  //
  // The one-time initial "fit everything" used to run off the library's own
  // onEngineStop event — but that fires the moment the (still default-weak)
  // simulation's alpha decays below threshold, which can happen before this
  // effect has even applied the stronger forces below. That race is what
  // produced a tight, overlapping zoomed-in ball: the camera locked onto the
  // old cramped bounding box, then the graph re-spread underneath it. Doing
  // the fit from right here — after the real forces are set and the
  // simulation is reheated, on a timer long enough for it to actually
  // re-settle — removes the race.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-320).distanceMax(2200);
    fg.d3Force("link")?.distance((link: { source: GNode; target: GNode }) => {
      const target = link.target as GNode;
      return radiusFor(target) * 9 + 40;
    });
    fg.d3Force("collide", forceCollide((node: GNode) => radiusFor(node) + 34));
    fg.d3ReheatSimulation();

    // Damped orbit controls turn scroll-wheel zoom into a decelerating glide
    // instead of a hard per-tick snap — the "smooth" half of the zoom
    // buttons' animated cameraPosition tween above.
    const controls = fg.controls() as { enableDamping?: boolean; dampingFactor?: number; zoomSpeed?: number };
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.zoomSpeed = 0.6;

    if (!hasFitRef.current && graphData.nodes.length > 1) {
      hasFitRef.current = true;
      const t = window.setTimeout(() => fgRef.current?.zoomToFit(700, 24), 1000);
      return () => window.clearTimeout(t);
    }
  }, [graphData.nodes.length]);

  // Dollies the camera toward/away from the current orbit target along the
  // existing camera->target ray, animated over the same transition length
  // used everywhere else (cameraPosition's own tween) rather than jumping —
  // that's what makes it read as "smooth" instead of a hard cut.
  const zoomBy = useCallback((factor: number) => {
    const fg = fgRef.current;
    if (!fg) return;
    const camera = fg.camera();
    const target = (fg.controls() as { target: THREE.Vector3 }).target;
    fg.cameraPosition(
      {
        x: target.x + (camera.position.x - target.x) * factor,
        y: target.y + (camera.position.y - target.y) * factor,
        z: target.z + (camera.position.z - target.z) * factor,
      },
      { x: target.x, y: target.y, z: target.z },
      450,
    );
  }, []);

  const goToNode = useCallback(
    (id: string) => {
      const node = nodesMap.get(id);
      if (!node) return;
      setSelected(node);
      setFocusedId(id);
      setHighlighted(null);
      setExplanation(null);
      const hasLoadedChildren = Array.from(nodesMap.values()).some((n) => n.parentId === id);
      focusCamera(id, node, hasLoadedChildren);
    },
    [nodesMap, focusCamera],
  );

  // Edges get the same neighborhood dimming as nodes (see activeIds above):
  // an edge blending into the background color reads as "not part of the
  // current view" without needing a separate opacity channel per link
  // (linkOpacity is a single graph-wide number in this library, not a
  // per-link accessor, so color is the lever available here).
  const isEdgeActive = useCallback(
    (l: GLink) => {
      if (!activeIds) return true;
      const source = l.source as unknown as string | GNode;
      const target = l.target as unknown as string | GNode;
      const s = typeof source === "object" ? source.id : source;
      const t = typeof target === "object" ? target.id : target;
      return activeIds.has(String(s)) && activeIds.has(String(t));
    },
    [activeIds],
  );

  const focusedChildren = useMemo(
    () => Array.from(nodesMap.values()).filter((n) => n.parentId === focusedId),
    [nodesMap, focusedId],
  );

  // Alphabetical directories — the graph itself sorts/sizes nodes by
  // transaction activity (that's what makes it a useful map), which makes a
  // specific area slow to hunt for by eye. These lists are a parallel A-Z
  // index into the exact same node set: picking a row drives the graph
  // (selectNode) exactly like clicking its sphere would.
  const allAreas = useMemo(
    () =>
      Array.from(nodesMap.values())
        .filter((n) => n.parentId === ROOT_NODE.id)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [nodesMap],
  );
  const subCommunities = useMemo(
    () =>
      focusedId === ROOT_NODE.id
        ? []
        : focusedChildren.filter((n) => n.type === "area").sort((a, b) => a.name.localeCompare(b.name)),
    [focusedChildren, focusedId],
  );

  const handleQuery = (q: string) => {
    const result = runQuery(q, Array.from(nodesMap.values()));
    setHighlighted(result.matchedIds.length ? new Set(result.matchedIds) : null);
    setExplanation(result.explanation);
  };

  return (
    <div className="intel-scope flex h-full w-full -m-6" style={{ height: "calc(100% + 3rem)" }}>
      <div ref={containerRef} className="relative flex-1 h-full overflow-hidden">
        <div className="absolute top-4 left-5 z-10 flex items-center gap-1.5 text-xs flex-wrap max-w-[70%]">
          <Link to="/" className="text-[var(--text-muted)] hover:text-[var(--text)]">Dubai</Link>
          {breadcrumbPath.slice(1).map((n, i) => (
            <span key={n.id} className="flex items-center gap-1.5">
              <span className="text-[var(--text-muted)]">/</span>
              <button
                onClick={() => goToNode(n.id)}
                className={i === breadcrumbPath.length - 2 ? "text-[var(--accent)] font-medium" : "text-[var(--text-muted)] hover:text-[var(--text)]"}
              >
                {n.name}
              </button>
            </span>
          ))}
          {loading && <span className="text-[var(--text-muted)] ml-2 animate-pulse">loading…</span>}
          {!loading && <span className="text-[var(--text-muted)] ml-2">— {nodesMap.size - 1} entities in view</span>}
        </div>

        <div className="absolute top-4 right-5 z-10 flex items-center gap-2">
          <button
            onClick={() => fgRef.current?.zoomToFit(700, 24)}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded-full px-3 py-1.5 bg-[var(--surface)]/80 backdrop-blur"
          >
            Fit All
          </button>
          {breadcrumbPath.length > 1 && (
            <button
              onClick={() => goToNode(breadcrumbPath[breadcrumbPath.length - 2].id)}
              className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded-full px-3 py-1.5 bg-[var(--surface)]/80 backdrop-blur"
            >
              &larr; Back
            </button>
          )}
        </div>

        <EntityListPanel
          allAreas={allAreas}
          subCommunities={subCommunities}
          subCommunityParentName={nodesMap.get(focusedId)?.name}
          focusedId={focusedId}
          onSelect={handleListSelect}
        />

        {size.width > 0 && (
          <ForceGraph3D
            ref={fgRef}
            graphData={graphData}
            width={size.width}
            height={size.height}
            backgroundColor={colors.background}
            nodeId="id"
            nodeThreeObject={nodeThreeObject}
            nodeThreeObjectExtend={false}
            nodeLabel={(n) => (n as GNode).name}
            onNodeClick={handleNodeClick}
            linkColor={(l) => (isEdgeActive(l as GLink) ? categoryColor((l as GLink).category, colors) : colors.background)}
            linkWidth={(l) => (pathEdgeIds.has(String((l as GLink).id)) ? 2.4 : (l as GLink).category === "default" ? 0.5 : 1)}
            linkOpacity={0.5}
            linkDirectionalParticles={(l) =>
              !isEdgeActive(l as GLink) ? 0 : pathEdgeIds.has(String((l as GLink).id)) ? 2 : (l as GLink).category === "default" ? 0 : 1
            }
            linkDirectionalParticleWidth={1.6}
            linkDirectionalParticleSpeed={0.006}
            enableNodeDrag={false}
            showNavInfo={false}
          />
        )}

        <ZoomControls onZoomIn={() => zoomBy(0.7)} onZoomOut={() => zoomBy(1.4)} />
        <EdgeLegend colors={colors} />
        <QueryBar onQuery={handleQuery} explanation={explanation} />
      </div>

      <div className="w-[340px] shrink-0">
        <IntelPanel node={selected ?? nodesMap.get(focusedId) ?? ROOT_NODE} children={focusedChildren} />
      </div>
    </div>
  );
}

/** A-Z directory of areas (and, once one is focused, its sub-communities)
 * living alongside the graph — picking a row drives the same selectNode
 * path a click on the sphere itself would, so the two ways of navigating
 * never fall out of sync. */
function EntityListPanel({
  allAreas,
  subCommunities,
  subCommunityParentName,
  focusedId,
  onSelect,
}: {
  allAreas: GNode[];
  subCommunities: GNode[];
  subCommunityParentName: string | undefined;
  focusedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="absolute top-16 right-5 z-10 w-64 flex flex-col gap-3">
      <div className="bg-[var(--surface)]/90 backdrop-blur border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="px-3 py-2 text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wide border-b border-[var(--border)]">
          Areas A–Z ({allAreas.length})
        </div>
        <div className="max-h-56 overflow-y-auto">
          {allAreas.map((n) => (
            <button
              key={n.id}
              onClick={() => onSelect(n.id)}
              className={`w-full text-left px-3 py-1.5 text-xs truncate hover:bg-[var(--bg)] ${
                n.id === focusedId ? "text-[var(--accent)] font-medium bg-[var(--bg)]" : "text-[var(--text)]"
              }`}
            >
              {n.name}
            </button>
          ))}
        </div>
      </div>

      {subCommunities.length > 0 && (
        <div className="bg-[var(--surface)]/90 backdrop-blur border border-[var(--border)] rounded-lg overflow-hidden">
          <div className="px-3 py-2 text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wide border-b border-[var(--border)]">
            {subCommunityParentName ?? "Sub-communities"} A–Z ({subCommunities.length})
          </div>
          <div className="max-h-56 overflow-y-auto">
            {subCommunities.map((n) => (
              <button
                key={n.id}
                onClick={() => onSelect(n.id)}
                className={`w-full text-left px-3 py-1.5 text-xs truncate hover:bg-[var(--bg)] ${
                  n.id === focusedId ? "text-[var(--accent)] font-medium bg-[var(--bg)]" : "text-[var(--text)]"
                }`}
              >
                {n.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ZoomControls({ onZoomIn, onZoomOut }: { onZoomIn: () => void; onZoomOut: () => void }) {
  const btnClass =
    "w-8 h-8 flex items-center justify-center text-base leading-none text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg)] transition-colors";
  return (
    <div className="absolute bottom-24 right-5 z-10 flex flex-col bg-[var(--surface)]/90 backdrop-blur border border-[var(--border)] rounded-lg overflow-hidden">
      <button onClick={onZoomIn} className={`${btnClass} border-b border-[var(--border)]`} aria-label="Zoom in" title="Zoom in">
        +
      </button>
      <button onClick={onZoomOut} className={btnClass} aria-label="Zoom out" title="Zoom out">
        &minus;
      </button>
    </div>
  );
}

function EdgeLegend({ colors }: { colors: IntelColorSet }) {
  const items = [
    { color: colors.accent, label: "Selected lineage (Dubai → focused node)" },
    { color: colors.good, label: "Opportunity — yield ≥ 7%" },
    { color: colors.bad, label: "Risk — yield < 4%" },
    { color: colors.edgeDefault, label: "No strong signal / no yield data" },
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
