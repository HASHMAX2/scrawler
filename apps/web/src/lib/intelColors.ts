/**
 * Three.js materials need real color values, not CSS custom-property
 * strings ("var(--x)" is meaningless to WebGL) — so the 3D graph keeps its
 * own light/dark hex maps here, kept in sync with the values in index.css.
 * This is the one place in the Intelligence Map that can't just read a CSS
 * var directly.
 */
import type { GraphNodeType } from "./graph";

export interface IntelColorSet {
  background: string;
  edgeDefault: string;
  accent: string;
  good: string;
  bad: string;
  text: string;
  node: Record<GraphNodeType, string>;
}

const LIGHT: IntelColorSet = {
  background: "#f8fafd",
  edgeDefault: "#c3d0dd",
  accent: "#2563eb",
  good: "#0f7a56",
  bad: "#c13b2e",
  text: "#172033",
  node: {
    market: "#2563eb",
    area: "#0f9488",
    project: "#b45309",
    developer: "#7c3aed",
    building: "#4338ca",
    unitType: "#0369a1",
  },
};

const DARK: IntelColorSet = {
  background: "#0c1722",
  edgeDefault: "#3a4d5e",
  accent: "#4b9bff",
  good: "#16a87a",
  bad: "#e9655a",
  text: "#f4f7fa",
  node: {
    market: "#4b9bff",
    area: "#34d5c4",
    project: "#f5a524",
    developer: "#8b5cf6",
    building: "#7580e0",
    unitType: "#38bdf8",
  },
};

export function intelColors(theme: "light" | "dark"): IntelColorSet {
  return theme === "dark" ? DARK : LIGHT;
}
