import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { motion } from "framer-motion";
import type { GraphNodeType, IntelNode } from "../../lib/graph";
import { circleOffsetX, sizeFor, type NodeEmphasis } from "./nodeLayout";

export type { NodeEmphasis };

export interface GraphNodeData extends Record<string, unknown> {
  node: IntelNode;
  emphasis: NodeEmphasis;
  // Selection is wired centrally via ReactFlow's onNodeClick (see
  // IntelligenceMap.tsx) — that's the reliable cross-input path. A nested
  // <button onClick> here would race React Flow's own pointer/drag
  // handling on the node wrapper and silently swallow real mouse clicks
  // (drag-threshold detection intercepts the pointerup before it bubbles
  // to a child element's click handler).
  onSelect: (node: IntelNode) => void;
}

const TYPE_COLOR: Record<GraphNodeType, string> = {
  market: "var(--node-market)",
  area: "var(--node-area)",
  project: "var(--node-project)",
  developer: "var(--node-developer)",
  building: "var(--node-infra)",
  unitType: "var(--node-unittype)",
};

function GraphNodeImpl({ data }: NodeProps) {
  const { node, emphasis } = data as GraphNodeData;
  const isMore = emphasis === "more";
  const color = isMore ? "var(--text-muted)" : TYPE_COLOR[node.type];
  const size = sizeFor(node.type, emphasis);
  const offsetX = circleOffsetX(size);
  const isFocused = emphasis === "focused";
  const isDimmed = emphasis === "dimmed";
  const isTrail = emphasis === "trail";
  const tooltip = [node.name, ...node.metrics.slice(0, 3).map((m) => `${m.label}: ${m.value}`)].join("\n");

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: isDimmed || isTrail ? 0.4 : 1, scale: 1 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-col items-center"
      style={{ width: 176 }}
      title={tooltip}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0, left: offsetX, top: size / 2 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0, left: offsetX + size, top: size / 2 }} />
      <div
        className={`relative flex items-center justify-center rounded-full transition-transform duration-300 hover:scale-[1.08] ${isMore ? "cursor-pointer border-dashed" : "cursor-pointer"}`}
        style={{
          width: size,
          height: size,
          marginLeft: offsetX,
          marginRight: offsetX,
          background: isMore
            ? "var(--surface-2)"
            : `radial-gradient(circle at 35% 28%, color-mix(in srgb, ${color} 24%, var(--surface-2)), var(--surface-2) 78%)`,
          border: isMore
            ? "1.5px dashed var(--border)"
            : `1.5px solid color-mix(in srgb, ${color} ${isFocused ? 70 : 42}%, var(--border))`,
          boxShadow: isFocused
            ? `0 0 0 1px color-mix(in srgb, ${color} 45%, transparent), 0 0 16px 2px color-mix(in srgb, ${color} 20%, transparent)`
            : emphasis === "child"
              ? `0 0 8px 0px color-mix(in srgb, ${color} 12%, transparent)`
              : "none",
        }}
      >
        <span
          className="font-bold tracking-tight text-center leading-none"
          style={{ color: isMore ? "var(--text-muted)" : "var(--text)", fontSize: isFocused ? 15 : size >= 60 ? 12 : 10 }}
        >
          {isMore ? `+${(node.raw as { remaining?: number })?.remaining ?? ""}` : node.shortCode}
        </span>
      </div>
      {!isMore && (
        <div className="mt-1.5 text-center" style={{ opacity: isDimmed || isTrail ? 0.55 : 1 }}>
          <div
            className="font-medium leading-tight px-1"
            style={{ color: "var(--text)", fontSize: isFocused ? 12.5 : 10.5 }}
          >
            {node.name.length > 20 ? `${node.name.slice(0, 19)}…` : node.name}
          </div>
          {node.badge && (
            <span
              className="inline-block mt-0.5 text-[9.5px] font-medium px-1.5 py-[1px] rounded-full"
              style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}
            >
              {node.badge}
            </span>
          )}
        </div>
      )}
      {isMore && <div className="mt-1.5 text-[10px] text-[var(--text-muted)]">View more</div>}
    </motion.div>
  );
}

export const GraphNode = memo(GraphNodeImpl);
