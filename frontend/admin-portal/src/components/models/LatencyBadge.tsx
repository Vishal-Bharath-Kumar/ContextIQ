import type { LatencyTier } from "../../services/modelService";

const TIER: Record<LatencyTier, { label: string; className: string }> = {
  fast: { label: "Fast", className: "badge-green" },
  medium: { label: "Medium", className: "badge-yellow" },
  slow: { label: "Slow", className: "badge-red" },
};

export function LatencyBadge({ tier }: { tier: LatencyTier }) {
  const { label, className } = TIER[tier];
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}
      aria-label={`Latency: ${label}`}
    >
      {label}
    </span>
  );
}
