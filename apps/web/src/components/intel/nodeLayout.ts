import type { GraphNodeType } from "../../lib/graph";

/** Every node's outer bounding box is this fixed width, with the circle
 * always horizontally centered inside it — regardless of circle diameter
 * or label length. This is what lets FloatingEdge compute exact circle-
 * boundary intersection points from just `size` (see circleOffsetX below)
 * instead of measuring rendered DOM, which would break the moment a label
 * wraps to a second line. */
export const NODE_BOX_WIDTH = 176;

export function circleOffsetX(size: number): number {
  return (NODE_BOX_WIDTH - size) / 2;
}

export type NodeEmphasis = "focused" | "parent" | "trail" | "child" | "more" | "dimmed";

/** Three visual tiers, per spec: root (90-110), primary/area entity
 * (60-72), child/leaf entity — project, building, developer, unit type
 * (44-58). Emphasis (focused/parent/trail) scales within those tiers. */
export function sizeFor(type: GraphNodeType, emphasis: NodeEmphasis): number {
  if (emphasis === "more") return 44;
  if (emphasis === "trail") return 36;
  if (type === "market") {
    return emphasis === "focused" ? 104 : emphasis === "parent" ? 64 : 48;
  }
  const isPrimary = type === "area";
  if (emphasis === "focused") return isPrimary ? 92 : 80;
  if (emphasis === "parent") return isPrimary ? 60 : 52;
  // child / dimmed
  return isPrimary ? 68 : 50;
}
