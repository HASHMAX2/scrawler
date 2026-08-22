import { createContext, useContext, useState, type ReactNode } from "react";

export type Period = "7d" | "30d" | "90d" | "6m" | "ytd";

interface FilterState {
  period: Period;
  setPeriod: (p: Period) => void;
}

const FilterContext = createContext<FilterState | null>(null);

export function FilterProvider({ children }: { children: ReactNode }) {
  const [period, setPeriod] = useState<Period>("90d");
  return <FilterContext.Provider value={{ period, setPeriod }}>{children}</FilterContext.Provider>;
}

export function useFilters(): FilterState {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used within FilterProvider");
  return ctx;
}

export const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "90d", label: "90D" },
  { value: "6m", label: "6M" },
  { value: "ytd", label: "YTD" },
];
