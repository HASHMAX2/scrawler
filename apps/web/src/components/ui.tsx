import type { ReactNode } from "react";
import { formatPct } from "../lib/format";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-[var(--border)] bg-[var(--surface)] ${className}`}>
      {children}
    </div>
  );
}

export function KpiCard({
  label, value, sub, changePct, confidence,
}: { label: string; value: string; sub?: string; changePct?: number | null; confidence?: string }) {
  const positive = (changePct ?? 0) >= 0;
  return (
    <Card className="p-4 flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className="text-2xl font-semibold text-[var(--text)]">{value}</div>
      <div className="flex items-center gap-2 text-xs">
        {changePct !== undefined && changePct !== null && (
          <span className={positive ? "text-[var(--good)]" : "text-[var(--bad)]"}>
            {positive ? "▲" : "▼"} {formatPct(Math.abs(changePct))}
          </span>
        )}
        {sub && <span className="text-[var(--text-muted)]">{sub}</span>}
        {confidence === "insufficient_data" && <ConfidenceBadge confidence={confidence} />}
      </div>
    </Card>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  if (confidence === "ok") return null;
  return (
    <span className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-[var(--warn)]/20 text-[var(--warn)] border border-[var(--warn)]/40">
      Insufficient Data
    </span>
  );
}

export function SignalBadge({ tone, children }: { tone: "good" | "bad" | "warn" | "neutral"; children: ReactNode }) {
  const colorMap = {
    good: "text-[var(--good)] bg-[var(--good)]/15 border-[var(--good)]/30",
    bad: "text-[var(--bad)] bg-[var(--bad)]/15 border-[var(--bad)]/30",
    warn: "text-[var(--warn)] bg-[var(--warn)]/15 border-[var(--warn)]/30",
    neutral: "text-[var(--text-muted)] bg-white/5 border-[var(--border)]",
  };
  return <span className={`rounded px-2 py-0.5 text-xs border ${colorMap[tone]}`}>{children}</span>;
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center text-[var(--text-muted)]">
      <div className="text-sm font-medium text-[var(--text)]">{title}</div>
      {detail && <div className="text-xs mt-1 max-w-md">{detail}</div>}
    </div>
  );
}

export function LoadingSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-10 rounded bg-[var(--surface-2)]" />
      ))}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <Card className="p-4 border-[var(--bad)]/40">
      <div className="text-sm text-[var(--bad)]">Error: {message}</div>
    </Card>
  );
}

export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-sm font-semibold text-[var(--text)] uppercase tracking-wide">{title}</h2>
      {action}
    </div>
  );
}

export function Select({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="bg-[var(--surface-2)] border border-[var(--border)] rounded px-2 py-1 text-sm text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
