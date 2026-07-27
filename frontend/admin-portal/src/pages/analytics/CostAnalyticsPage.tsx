import { useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useCostAnalytics } from "../../services/modelService";
import { PageHeader } from "../../components/ui/PageHeader";
import { GlassCard } from "../../components/ui/GlassCard";
import { StatCard } from "../../components/ui/StatCard";
import { TokensIcon } from "@radix-ui/react-icons";

const TIME_RANGES = [
  { label: "Last 7 Days", value: 7 },
  { label: "Last 30 Days", value: 30 },
  { label: "Last 90 Days", value: 90 },
] as const;

const MODEL_COLORS = [
  "#6366f1", // indigo
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#f59e0b", // amber
  "#10b981", // emerald
  "#3b82f6", // blue
  "#ef4444", // red
  "#06b6d4", // cyan
];

export function CostAnalyticsPage() {
  const [days, setDays] = useState<number>(30);
  const { data: summaries, isLoading } = useCostAnalytics(days);

  const totalSpend = summaries?.reduce((sum, s) => sum + s.total_cost_usd, 0) ?? 0;
  const totalTokens = summaries?.reduce((sum, s) => sum + s.total_tokens, 0) ?? 0;
  const avgCostPerModel = summaries && summaries.length > 0 ? totalSpend / summaries.length : 0;
  const topModel = summaries && summaries.length > 0 ? summaries[0] : null;

  // Prepare data for stacked area chart (daily spend by model)
  const dailyData = prepareDailyStackedData(summaries ?? []);

  // Model comparison bar chart
  const modelComparison =
    summaries?.map((s) => ({
      model_id: s.model_id.split("/").pop() ?? s.model_id, // Shorten name
      total_cost_usd: s.total_cost_usd,
      total_tokens: s.total_tokens,
      avg_cost_per_1k: s.total_tokens > 0 ? (s.total_cost_usd / s.total_tokens) * 1000 : 0,
    })) ?? [];

  return (
    <main aria-labelledby="cost-analytics-heading" className="page-layout">
      <PageHeader
        headingId="cost-analytics-heading"
        title="LLM Cost Analytics"
        subtitle="Track AI spend, token usage, and cost trends across all models."
      />

      {/* Time range selector */}
      <div className="mb-6 flex items-center gap-2">
        <span className="text-sm font-medium text-slate-700">Time Range:</span>
        {TIME_RANGES.map((range) => (
          <button
            key={range.value}
            onClick={() => setDays(range.value)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              days === range.value
                ? "bg-primary text-white shadow-sm"
                : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {range.label}
          </button>
        ))}
      </div>

      {isLoading && (
        <p role="status" aria-live="polite" className="py-8 text-secondary">
          Loading cost analytics…
        </p>
      )}

      {!isLoading && (
        <div className="space-y-6">
          {/* KPIs */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Total LLM Spend"
              value={totalSpend}
              decimals={2}
              prefix="$"
              icon={<TokensIcon />}
              accent="danger"
              delay={0}
            />
            <StatCard
              label="Total Tokens"
              value={totalTokens}
              icon={<TokensIcon />}
              accent="info"
              delay={40}
            />
            <StatCard
              label="Avg Cost per Model"
              value={avgCostPerModel}
              decimals={2}
              prefix="$"
              icon={<TokensIcon />}
              accent="warning"
              delay={80}
            />
            <StatCard
              label="Most Used Model"
              value={0}
              suffix={topModel ? ` ${topModel.model_id.split("/").pop()}` : " N/A"}
              icon={<TokensIcon />}
              accent="success"
              delay={120}
            />
          </div>

          {/* Daily spend trend (stacked by model) */}
          <GlassCard className="p-6" delay={160}>
            <h2 className="mb-4 text-base font-semibold text-slate-800">
              Daily Spend Trend by Model (Last {days} Days)
            </h2>
            {dailyData.length === 0 ? (
              <p className="py-10 text-center text-sm text-secondary">No cost data for this period.</p>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={dailyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={16} />
                  <YAxis tick={{ fontSize: 11 }} width={60} tickFormatter={(v) => `$${v.toFixed(2)}`} />
                  <Tooltip
                    formatter={(v: number) => [`$${v.toFixed(4)}`, ""]}
                    labelStyle={{ color: "#1e293b" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {summaries?.map((s, idx) => (
                    <Line
                      key={s.model_id}
                      type="monotone"
                      dataKey={s.model_id}
                      stroke={MODEL_COLORS[idx % MODEL_COLORS.length]}
                      strokeWidth={2}
                      dot={false}
                      name={s.model_id.split("/").pop() ?? s.model_id}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
          </GlassCard>

          {/* Model comparison bar chart */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <GlassCard className="p-6" delay={200}>
              <h2 className="mb-4 text-base font-semibold text-slate-800">Total Spend by Model</h2>
              {modelComparison.length === 0 ? (
                <p className="py-10 text-center text-sm text-secondary">No models tracked yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={modelComparison} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                    <YAxis
                      type="category"
                      dataKey="model_id"
                      tick={{ fontSize: 10 }}
                      width={100}
                      className="truncate"
                    />
                    <Tooltip formatter={(v: number) => `$${v.toFixed(4)}`} />
                    <Bar dataKey="total_cost_usd" radius={[0, 4, 4, 0]}>
                      {modelComparison.map((_, idx) => (
                        <Cell key={`cell-${idx}`} fill={MODEL_COLORS[idx % MODEL_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </GlassCard>

            <GlassCard className="p-6" delay={240}>
              <h2 className="mb-4 text-base font-semibold text-slate-800">Token Usage by Model</h2>
              {modelComparison.length === 0 ? (
                <p className="py-10 text-center text-sm text-secondary">No token data yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={modelComparison} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`} />
                    <YAxis
                      type="category"
                      dataKey="model_id"
                      tick={{ fontSize: 10 }}
                      width={100}
                    />
                    <Tooltip formatter={(v: number) => v.toLocaleString()} />
                    <Bar dataKey="total_tokens" radius={[0, 4, 4, 0]}>
                      {modelComparison.map((_, idx) => (
                        <Cell key={`cell-${idx}`} fill={MODEL_COLORS[idx % MODEL_COLORS.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </GlassCard>
          </div>

          {/* Detailed table */}
          <GlassCard className="p-6" delay={280}>
            <h2 className="mb-4 text-base font-semibold text-slate-800">Detailed Cost Breakdown</h2>
            {modelComparison.length === 0 ? (
              <p className="py-10 text-center text-sm text-secondary">No data available.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-slate-50 text-left text-xs uppercase text-slate-600">
                      <th className="px-4 py-3">Model</th>
                      <th className="px-4 py-3 text-right">Total Spend</th>
                      <th className="px-4 py-3 text-right">Total Tokens</th>
                      <th className="px-4 py-3 text-right">Avg Cost per 1K</th>
                      <th className="px-4 py-3 text-right">% of Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelComparison.map((model, idx) => {
                      const pctOfTotal = totalSpend > 0 ? (model.total_cost_usd / totalSpend) * 100 : 0;
                      return (
                        <tr key={model.model_id} className="border-t hover:bg-slate-50/50">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <div
                                className="h-3 w-3 rounded-full"
                                style={{ backgroundColor: MODEL_COLORS[idx % MODEL_COLORS.length] }}
                              />
                              <span className="font-mono text-xs">{model.model_id}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right font-semibold">
                            ${model.total_cost_usd.toFixed(4)}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            {model.total_tokens.toLocaleString()}
                          </td>
                          <td className="px-4 py-3 text-right text-slate-600">
                            ${model.avg_cost_per_1k.toFixed(6)}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className="font-medium">{pctOfTotal.toFixed(1)}%</span>
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="border-t-2 border-slate-300 bg-slate-50 font-semibold">
                      <td className="px-4 py-3">Total</td>
                      <td className="px-4 py-3 text-right">${totalSpend.toFixed(4)}</td>
                      <td className="px-4 py-3 text-right">{totalTokens.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right">—</td>
                      <td className="px-4 py-3 text-right">100%</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>
        </div>
      )}
    </main>
  );
}

// Helper: Transform per-model daily series into a single array with one entry per date
// containing all model costs for that date
function prepareDailyStackedData(summaries: Array<{ model_id: string; daily_series: Array<{ date: string; cost_usd: number }> }>) {
  if (summaries.length === 0) return [];

  const dateMap = new Map<string, Record<string, number | string>>();

  for (const summary of summaries) {
    for (const point of summary.daily_series) {
      if (!dateMap.has(point.date)) {
        dateMap.set(point.date, { date: point.date });
      }
      const entry = dateMap.get(point.date)!;
      entry[summary.model_id] = point.cost_usd;
    }
  }

  return Array.from(dateMap.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
}
