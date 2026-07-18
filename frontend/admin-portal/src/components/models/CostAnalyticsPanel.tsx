import { LineChart, Line, ResponsiveContainer, Tooltip } from "recharts";
import { useCostAnalytics } from "../../services/modelService";
import type { ModelCostSummary, DailyCostPoint } from "../../services/modelService";

export function CostAnalyticsPanel() {
  const { data: summaries, isLoading } = useCostAnalytics(30);

  return (
    <section aria-labelledby="cost-panel-heading" className="mt-8">
      <h2 id="cost-panel-heading" className="text-lg font-semibold mb-4">
        Cost Analytics — Last 30 Days
      </h2>

      {isLoading && (
        <p role="status" aria-live="polite">
          Loading cost data…
        </p>
      )}

      {summaries && summaries.length === 0 && (
        <p className="text-sm text-gray-400">No LLM cost data recorded yet.</p>
      )}

      {summaries && summaries.length > 0 && (
        <table
          className="w-full border-collapse text-sm"
          aria-label="30-day LLM cost per model"
        >
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase bg-gray-50">
              <th scope="col" className="px-4 py-2">
                Model
              </th>
              <th scope="col" className="px-4 py-2">
                30-day spend
              </th>
              <th scope="col" className="px-4 py-2">
                Total tokens
              </th>
              <th scope="col" className="px-4 py-2 w-40">
                Trend
              </th>
            </tr>
          </thead>
          <tbody>
            {summaries.map((s) => (
              <ModelCostRow key={s.model_id} summary={s} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ModelCostRow({ summary }: { summary: ModelCostSummary }) {
  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="px-4 py-2 font-mono text-xs">{summary.model_id}</td>
      <td className="px-4 py-2 font-semibold">
        ${summary.total_cost_usd.toFixed(2)}
      </td>
      <td className="px-4 py-2 text-gray-500">
        {summary.total_tokens.toLocaleString()}
      </td>
      <td className="px-4 py-2">
        {/* AC-4: trend sparkline — narrow LineChart without axes */}
        <CostSparkline series={summary.daily_series} />
      </td>
    </tr>
  );
}

function CostSparkline({ series }: { series: DailyCostPoint[] }) {
  const hasData = series.some((p) => p.cost_usd > 0);

  return (
    <div
      className="h-8 w-36"
      aria-label={`Daily cost trend over last ${series.length} days`}
      role="img"
    >
      {hasData ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series}>
            <Tooltip
              formatter={(v: number) => [`$${v.toFixed(4)}`, "Cost"]}
              labelFormatter={(label) => String(label)}
            />
            <Line
              type="monotone"
              dataKey="cost_usd"
              dot={false}
              strokeWidth={1.5}
              stroke="#2563EB"
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <span className="text-xs text-gray-300">No data</span>
      )}
    </div>
  );
}
