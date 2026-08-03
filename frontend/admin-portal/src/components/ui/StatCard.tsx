import type { ReactNode } from "react";
import { AnimatedCounter } from "./AnimatedCounter";

interface Props {
  label: string;
  value: number;
  decimals?: number;
  suffix?: string;
  prefix?: string;
  icon?: ReactNode;
  accent?: "primary" | "success" | "warning" | "danger" | "info";
  trend?: { value: number; label: string } | null;
  delay?: number;
}

const ACCENTS: Record<NonNullable<Props["accent"]>, string> = {
  primary: "from-primary-500 to-primary-700",
  success: "from-emerald-400 to-emerald-600",
  warning: "from-amber-400 to-amber-600",
  danger: "from-red-400 to-red-600",
  info: "from-sky-400 to-sky-600",
};

/** KPI stat card with animated count-up value and gradient icon chip. */
export function StatCard({
  label,
  value,
  decimals = 0,
  suffix = "",
  prefix = "",
  icon,
  accent = "primary",
  trend,
  delay = 0,
}: Props) {
  return (
    <div
      className="glass-card animate-slide-up p-5"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-secondary">{label}</p>
          <p className="mt-2 text-3xl font-bold tracking-tight text-slate-900">
            <AnimatedCounter value={value} decimals={decimals} suffix={suffix} prefix={prefix} />
          </p>
          {trend && (
            <p
              className={`mt-1 text-xs font-medium ${
                trend.value >= 0 ? "text-emerald-600" : "text-red-600"
              }`}
            >
              {trend.value >= 0 ? "▲" : "▼"} {Math.abs(trend.value)}% {trend.label}
            </p>
          )}
        </div>
        {icon && (
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${ACCENTS[accent]} text-white shadow-glow-sm`}
            aria-hidden="true"
          >
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
