import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import { Card, SectionHeader } from "./ui";

const PALETTE = ["#c98a4b", "#8ba888", "#c0685c", "#c9a24b", "#9a7fb5", "#6a9db0"];

export function baseTheme(): Partial<EChartsOption> {
  return {
    color: PALETTE,
    backgroundColor: "transparent",
    textStyle: { color: "#b3a190", fontFamily: "inherit" },
    grid: { left: 48, right: 16, top: 24, bottom: 32 },
    tooltip: {
      backgroundColor: "#241c16",
      borderColor: "#382c22",
      textStyle: { color: "#f2e9dd" },
    },
    legend: { textStyle: { color: "#b3a190" } },
  };
}

export function ChartCard({ title, option, height = 280 }: { title: string; option: EChartsOption; height?: number }) {
  return (
    <Card className="p-4">
      <SectionHeader title={title} />
      <ReactECharts option={{ ...baseTheme(), ...option }} style={{ height }} notMerge lazyUpdate />
    </Card>
  );
}
