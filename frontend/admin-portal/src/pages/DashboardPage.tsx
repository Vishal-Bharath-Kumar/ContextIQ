import { useMemo } from "react";
import { Link } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArchiveIcon,
  CardStackIcon,
  LockClosedIcon,
  Share2Icon,
  TokensIcon,
  WidthIcon,
} from "@radix-ui/react-icons";

import { useAuth } from "../context/AuthContext";
import { useConnectors } from "../services/connectorService";
import { useCostAnalytics, useModels } from "../services/modelService";
import { usePolicies } from "../services/policyService";
import { useAuditLog } from "../services/auditLogService";
import { useTools } from "../services/toolRegistryService";
import { StatCard } from "../components/ui/StatCard";
import { PageHeader } from "../components/ui/PageHeader";
import { GlassCard } from "../components/ui/GlassCard";
import { EmptyState } from "../components/ui/EmptyState";
import { CostAnalyticsPanel } from "../components/models/CostAnalyticsPanel";

const CONNECTOR_STATUS_COLORS: Record<string, string> = {
  active: "#10b981",
  syncing: "#0ea5e9",
  inactive: "#94a3b8",
  error: "#ef4444",
};

const LATENCY_COLORS: Record<string, string> = {
  fast: "#10b981",
  medium: "#f59e0b",
  slow: "#ef4444",
};

const SUCCESS_METRICS = [
  { label: "Context Retrieval Accuracy", target: "≥ 95%", pct: 95 },
  { label: "Token Reduction", target: "≥ 80%", pct: 80 },
  { label: "AI Cost Reduction", target: "≥ 60%", pct: 60 },
  { label: "Policy Compliance", target: "100%", pct: 100 },
  { label: "Platform Uptime", target: "≥ 99.9%", pct: 99.9 },
];

export function DashboardPage() {
  const { user } = useAuth();
  const { data: connectors, isLoading: connectorsLoading } = useConnectors();
  const { data: models, isLoading: modelsLoading } = useModels();
  const { data: policies, isLoading: policiesLoading } = usePolicies();
  const { data: costSummaries, isLoading: costLoading } = useCostAnalytics(30);
  const { data: auditPages } = useAuditLog({});
  const { data: tools, isLoading: toolsLoading } = useTools();

  const isLoading = connectorsLoading || modelsLoading || policiesLoading || costLoading || toolsLoading;

  const activeConnectors = connectors?.filter((c) => c.status === "active").length ?? 0;
  const totalDocuments = connectors?.reduce((sum, c) => sum + c.document_count, 0) ?? 0;
  const activeModels = models?.filter((m) => m.is_active).length ?? 0;
  const enforcedPolicies = policies?.filter((p) => p.active_version).length ?? 0;
  const activeTools = tools?.filter((t) => t.status === "active").length ?? 0;
  const totalSpend = costSummaries?.reduce((sum, s) => sum + s.total_cost_usd, 0) ?? 0;
  const totalTokens = costSummaries?.reduce((sum, s) => sum + s.total_tokens, 0) ?? 0;

  const spendTrend = useMemo(() => {
    if (!costSummaries || costSummaries.length === 0) return [];
    const byDate = new Map<string, number>();
    for (const summary of costSummaries) {
      for (const point of summary.daily_series) {
        byDate.set(point.date, (byDate.get(point.date) ?? 0) + point.cost_usd);
      }
    }
    return Array.from(byDate.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, cost_usd]) => ({ date, cost_usd: Math.round(cost_usd * 10000) / 10000 }));
  }, [costSummaries]);

  const connectorStatusData = useMemo(() => {
    if (!connectors) return [];
    const counts = new Map<string, number>();
    for (const c of connectors) counts.set(c.status, (counts.get(c.status) ?? 0) + 1);
    return Array.from(counts.entries()).map(([status, count]) => ({ status, count }));
  }, [connectors]);

  const latencyTierData = useMemo(() => {
    if (!models) return [];
    const counts = new Map<string, number>();
    for (const m of models) counts.set(m.latency_tier, (counts.get(m.latency_tier) ?? 0) + 1);
    return Array.from(counts.entries()).map(([tier, count]) => ({ tier, count }));
  }, [models]);

  const recentActivity = auditPages?.pages[0]?.items?.slice(0, 6) ?? [];

  return (
    <main aria-labelledby="dashboard-heading" className="page-layout">
      <PageHeader
        headingId="dashboard-heading"
        title={`Welcome back${user?.name ? `, ${user.name.split(" ")[0]}` : ""}`}
        subtitle="Enterprise AI context, governance, and cost overview at a glance."
      />

      {isLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading dashboard…
        </p>
      )}

      {!isLoading && (
        <div className="space-y-6">
          {/* KPI row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7">
            <StatCard
              label="Active Connectors"
              value={activeConnectors}
              suffix={` / ${connectors?.length ?? 0}`}
              icon={<Share2Icon />}
              accent="info"
              delay={0}
            />
            <StatCard
              label="Documents Indexed"
              value={totalDocuments}
              icon={<ArchiveIcon />}
              accent="primary"
              delay={40}
            />
            <StatCard
              label="Active Models"
              value={activeModels}
              suffix={` / ${models?.length ?? 0}`}
              icon={<CardStackIcon />}
              accent="success"
              delay={80}
            />
            <StatCard
              label="Policies Enforced"
              value={enforcedPolicies}
              suffix={` / ${policies?.length ?? 0}`}
              icon={<LockClosedIcon />}
              accent="warning"
              delay={120}
            />
            <StatCard
              label="Active Tools"
              value={activeTools}
              suffix={` / ${tools?.length ?? 0}`}
              icon={<WidthIcon />}
              accent="primary"
              delay={160}
            />
            <StatCard
              label="30-Day LLM Spend"
              value={totalSpend}
              decimals={2}
              prefix="$"
              icon={<TokensIcon />}
              accent="danger"
              delay={200}
            />
            <StatCard
              label="Tokens Processed"
              value={totalTokens}
              icon={<TokensIcon />}
              accent="info"
              delay={240}
            />
          </div>

          {/* Charts row */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <GlassCard className="p-5 lg:col-span-2" delay={80}>
              <h2 className="mb-4 text-sm font-semibold text-slate-800">30-Day LLM Spend Trend</h2>
              {spendTrend.length === 0 ? (
                <p className="py-10 text-center text-sm text-secondary">No cost data recorded yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={spendTrend}>
                    <defs>
                      <linearGradient id="spendFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#6366f1" stopOpacity={0.45} />
                        <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={24} />
                    <YAxis tick={{ fontSize: 11 }} width={50} tickFormatter={(v) => `$${v}`} />
                    <Tooltip formatter={(v: number) => [`$${v.toFixed(4)}`, "Spend"]} />
                    <Area
                      type="monotone"
                      dataKey="cost_usd"
                      stroke="#4f46e5"
                      strokeWidth={2}
                      fill="url(#spendFill)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </GlassCard>

            <GlassCard className="p-5" delay={120}>
              <h2 className="mb-4 text-sm font-semibold text-slate-800">Connector Health</h2>
              {connectorStatusData.length === 0 ? (
                <p className="py-10 text-center text-sm text-secondary">No connectors configured.</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={connectorStatusData}
                      dataKey="count"
                      nameKey="status"
                      innerRadius={55}
                      outerRadius={85}
                      paddingAngle={3}
                    >
                      {connectorStatusData.map((entry) => (
                        <Cell key={entry.status} fill={CONNECTOR_STATUS_COLORS[entry.status] ?? "#6366f1"} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend
                      formatter={(v: string) => <span className="text-xs capitalize">{v}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </GlassCard>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <GlassCard className="p-5" delay={160}>
              <h2 className="mb-4 text-sm font-semibold text-slate-800">Model Latency Mix</h2>
              {latencyTierData.length === 0 ? (
                <p className="py-10 text-center text-sm text-secondary">No models registered yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={latencyTierData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
                    <XAxis dataKey="tier" tick={{ fontSize: 12 }} className="capitalize" />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={30} />
                    <Tooltip />
                    <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                      {latencyTierData.map((entry) => (
                        <Cell key={entry.tier} fill={LATENCY_COLORS[entry.tier] ?? "#6366f1"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
              <div className="mt-3 flex justify-end">
                <Link to="/models" className="text-xs font-medium text-primary hover:underline">
                  Manage models →
                </Link>
              </div>
            </GlassCard>

            <GlassCard className="p-5" delay={200}>
              <h2 className="mb-4 text-sm font-semibold text-slate-800">Recent Activity</h2>
              {recentActivity.length === 0 ? (
                <p className="py-10 text-center text-sm text-secondary">No audit events recorded yet.</p>
              ) : (
                <ul className="space-y-3 text-sm">
                  {recentActivity.map((entry) => (
                    <li key={entry.id} className="flex items-start gap-2 border-l-2 border-primary-200 pl-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-700">{entry.action}</p>
                        <p className="text-xs text-secondary">
                          {entry.resource_type} · {formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true })}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 flex justify-end">
                <Link to="/audit-log" className="text-xs font-medium text-primary hover:underline">
                  View audit log →
                </Link>
              </div>
            </GlassCard>

            <GlassCard className="p-5" delay={240}>
              <h2 className="mb-4 text-sm font-semibold text-slate-800">BRD Success Metric Targets</h2>
              <ul className="space-y-3">
                {SUCCESS_METRICS.map((metric) => (
                  <li key={metric.label}>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="font-medium text-slate-700">{metric.label}</span>
                      <span className="font-mono text-secondary">{metric.target}</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200/70">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-primary-400 to-primary-600 animate-glow-pulse"
                        style={{ width: `${Math.min(metric.pct, 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </GlassCard>
          </div>

          {/* Per-model cost breakdown with sparklines */}
          <CostAnalyticsPanel />

          {connectors && connectors.length === 0 && models?.length === 0 && (
            <EmptyState
              title="Let's get ContextIQ set up"
              description="Add your first connector and model to start seeing live enterprise context metrics here."
              action={
                <Link to="/connectors/add" className="btn-primary">
                  Add a connector
                </Link>
              }
            />
          )}
        </div>
      )}
    </main>
  );
}
