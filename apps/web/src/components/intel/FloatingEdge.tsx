import { BaseEdge, useInternalNode, type EdgeProps } from "@xyflow/react";
import type { GraphNodeData } from "./GraphNode";
import { circleOffsetX, sizeFor } from "./nodeLayout";

/**
 * Edges here are NOT manually-positioned CSS lines — this is a real
 * ReactFlow edge that recomputes its endpoints from each node's live
 * position/size on every render (useInternalNode subscribes to node
 * moves). It draws the line between the two nodes' actual CIRCLE
 * boundaries (not the outer label box, and not a generic Left/Right
 * handle point), so it visually touches both circles regardless of pan,
 * zoom, resize, or which side of the target the source happens to be on.
 */
function circleCenter(internalNode: NonNullable<ReturnType<typeof useInternalNode>>) {
  const { node, emphasis } = internalNode.data as GraphNodeData;
  const size = sizeFor(node.type, emphasis);
  const offsetX = circleOffsetX(size);
  const pos = internalNode.internals.positionAbsolute;
  return { x: pos.x + offsetX + size / 2, y: pos.y + size / 2, radius: size / 2 };
}

export function FloatingEdge({ id, source, target, style, markerEnd }: EdgeProps) {
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);
  if (!sourceNode || !targetNode) return null;

  const s = circleCenter(sourceNode);
  const t = circleCenter(targetNode);
  const dx = t.x - s.x;
  const dy = t.y - s.y;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;

  const sx = s.x + ux * s.radius;
  const sy = s.y + uy * s.radius;
  const tx = t.x - ux * t.radius;
  const ty = t.y - uy * t.radius;

  const path = `M ${sx},${sy} L ${tx},${ty}`;

  // React Flow wraps every edge (custom types included) in a
  // `react-flow__edge` <g> and appends `animated` there when edge.animated
  // is true, so the built-in dashed-stroke CSS on `.react-flow__edge.animated
  // path` applies automatically — nothing extra needed here.
  return <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />;
}
