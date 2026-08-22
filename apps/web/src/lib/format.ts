export function formatAed(value: number | null | undefined): string {
  if (value === null || value === undefined) return "N/A";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000_000) return `${sign}AED ${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${sign}AED ${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}AED ${(abs / 1_000).toFixed(0)}K`;
  return `${sign}AED ${abs.toFixed(0)}`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "N/A";
  return value.toLocaleString("en-US");
}

export function formatPct(value: number | null | undefined, opts?: { withSign?: boolean }): string {
  if (value === null || value === undefined) return "N/A";
  const sign = opts?.withSign && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function formatPsf(value: number | null | undefined): string {
  if (value === null || value === undefined) return "N/A";
  return `AED ${value.toFixed(0)}/sqft`;
}
