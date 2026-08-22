import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { motion } from "framer-motion";
import type { GraphNodeType, IntelNode } from "../../lib/graph";

export type NodeEmphasis = "focused" | "parent" | "child" | "dimmed";

export interface GraphNodeData extends Record<string, unknown> {
  node: IntelNode;
  emphasis: NodeEmphasis;
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

const SIZE: Record<NodeEmphasis, number> = {
  focused: 108,
  parent: 68,
  child: 84,
  dimmed: 60,
};

function GraphNodeImpl({ data }: NodeProps) {
  const { node, emphasis, onSelect } = data as GraphNodeData;
  const color = TYPE_COLOR[node.type];
  const size = SIZE[emphasis];
  const isFocused = emphasis === "focused";
  const isDimmed = emphasis === "dimmed";

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.7 }}
      animate={{ opacity: isDimmed ? 0.35 : 1, scale: 1 }}
      transition={{ duration: 0.45, ease: "easeOut" }}
      className="flex flex-col items-center"
      style={{ width: size + 90 }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <button
        onClick={() => onSelect(node)}
        className="relative flex items-center justify-center rounded-full transition-transform duration-300 hover:scale-[1.06] cursor-pointer"
        style={{
          width: size,
          height: size,
          background: `radial-gradient(circle at 35% 30%, color-mix(in srgb, ${color} 32%, var(--surface-2)), var(--surface-2) 75%)`,
          border: `1.5px solid color-mix(in srgb, ${color} ${isFocused ? 85 : 45}%, var(--border))`,
          boxShadow: isFocused
            ? `0 0 0 1px color-mix(in srgb, ${color} 55%, transparent), 0 0 32px 4px color-mix(in srgb, ${color} 45%, transparent)`
            : emphasis === "child"
              ? `0 0 14px 1px color-mix(in srgb, ${color} 22%, transparent)`
              : "none",
        }}
      >
        <span
          className="font-semibold tracking-tight text-center leading-tight px-1"
          style={{ color: "var(--text)", fontSize: isFocused ? 12 : emphasis === "parent" ? 9 : 10.5 }}
        >
          {node.name.length > 14 && !isFocused ? `${node.name.slice(0, 13)}…` : node.name}
        </span>
      </button>
      {node.badge && (
        <span
          className="mt-1.5 text-[10px] font-medium px-2 py-0.5 rounded-full"
          style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)`, opacity: isDimmed ? 0.5 : 1 }}
        >
          {node.badge}
        </span>
      )}
      {!node.badge && !isFocused && (
        <span className="mt-1.5 text-[9px] uppercase tracking-wide" style={{ color: "var(--text-muted)", opacity: isDimmed ? 0.5 : 1 }}>
          {node.subtitle ?? node.type}
        </span>
      )}
    </motion.div>
  );
}

export const GraphNode = memo(GraphNodeImpl);
