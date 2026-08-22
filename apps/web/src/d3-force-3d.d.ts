declare module "d3-force-3d" {
  export function forceCollide<T>(
    radius: number | ((node: T) => number),
  ): ((alpha: number) => void) & {
    initialize?: (nodes: T[], ...args: unknown[]) => void;
    strength(s: number): unknown;
    iterations(i: number): unknown;
  };
}
