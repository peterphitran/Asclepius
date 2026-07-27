"use client";

import { Bar, BarChart, Cell, XAxis, YAxis } from "recharts";

import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { ALL_CATEGORIES, CATEGORY_META, SEVERITY_META, SEVERITY_ORDER } from "@/lib/display";
import type { Finding } from "@/lib/types";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#f59e0b",
  low: "#0ea5e9",
  info: "#64748b",
};

const chartConfig = {
  count: { label: "Findings" },
} satisfies ChartConfig;

export function SeverityChart({ findings }: { findings: Finding[] }) {
  const severityData = SEVERITY_ORDER.map((severity) => ({
    key: severity,
    label: SEVERITY_META[severity].label,
    count: findings.filter((f) => f.severity === severity).length,
    fill: SEVERITY_COLORS[severity],
  }));

  return (
    <ChartContainer config={chartConfig} className="h-55 w-full">
      <BarChart accessibilityLayer data={severityData}>
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          className="text-xs"
        />
        <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
        <Bar dataKey="count" radius={6}>
          {severityData.map((entry) => (
            <Cell key={entry.key} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

export function CategoryChart({ findings }: { findings: Finding[] }) {
  const categoryData = ALL_CATEGORIES.map((category) => ({
    key: category,
    label: CATEGORY_META[category].short,
    count: findings.filter((f) => f.category === category).length,
  }));

  return (
    <ChartContainer config={chartConfig} className="h-55 w-full">
      <BarChart
        accessibilityLayer
        data={categoryData}
        layout="vertical"
        margin={{ left: 8, right: 16 }}
      >
        <YAxis
          dataKey="label"
          type="category"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          width={80}
          className="text-xs"
        />
        <XAxis dataKey="count" type="number" hide />
        <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
        <Bar dataKey="count" radius={6} fill="#8b5cf6" />
      </BarChart>
    </ChartContainer>
  );
}
