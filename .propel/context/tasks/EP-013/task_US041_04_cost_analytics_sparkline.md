# TASK-US041-04 — 30-Day Cost Analytics Backend Route and Trend Sparkline Panel

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US041-04 |
| User Story | US-041 |
| Epic | EP-013 — Administration Portal |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement `GET /v1/models/cost-analytics?days=30` (AC-4) that queries the Langfuse API for LLM generation records over the last N days, aggregates per-model daily spend into a sparkline series, and returns a summary per model. The `CostAnalyticsPanel` frontend component renders a per-model table row with a 30-day total and a `Recharts` `<Sparkline>` (a narrow `<LineChart>` without axes). US-037 TASK-US037-01 already sends every LLM call to Langfuse via `LLMCostRecorder.record_llm_call()` — this task consumes that data through the Langfuse SDK.

## Implementation Details

**Technology (backend):** Python 3.11+, FastAPI, `langfuse>=2.0` (`Langfuse().observations()`), `pydantic-settings`

**Technology (frontend):** React 18, TypeScript, TanStack Query v5, `recharts>=2.12`

**File locations:**
- `src/observability/cost/analytics_service.py` — `ModelCostAnalyticsService`
- `src/api/admin/routes/model_analytics.py` — FastAPI router
- `src/api/admin/router.py` — include new router (extend)
- `frontend/admin-portal/src/pages/models/ModelListPage.tsx` — extend with analytics panel tab
- `frontend/admin-portal/src/components/models/CostAnalyticsPanel.tsx`
- `frontend/admin-portal/src/services/modelService.ts` — extend with `useCostAnalytics`

---

### Pydantic schemas

```python
# src/observability/cost/analytics_service.py  (top of file)
from __future__ import annotations
from datetime   import date, datetime, timedelta, timezone
from pydantic   import BaseModel, ConfigDict


class DailyCostPoint(BaseModel):
    model_config = ConfigDict(frozen=True)
    date:     date
    cost_usd: float


class ModelCostSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id:       str
    total_cost_usd: float             # sum over the requested window
    daily_series:   list[DailyCostPoint]   # one entry per calendar day, oldest-first
    total_tokens:   int
```

---

### `ModelCostAnalyticsService`

```python
# src/observability/cost/analytics_service.py  (continued)
import logging
from collections import defaultdict
from langfuse     import Langfuse
from src.config   import settings   # pydantic-settings; LANGFUSE_* env vars

logger = logging.getLogger(__name__)


class ModelCostAnalyticsService:
    """
    Queries Langfuse for GENERATION observations over the last `days` calendar days
    and aggregates them by model_id and calendar date.
    """

    def __init__(self) -> None:
        self._langfuse = Langfuse(
            public_key  = settings.langfuse_public_key,
            secret_key  = settings.langfuse_secret_key,
            host        = settings.langfuse_host,
        )

    async def get_model_cost_summary(self, days: int = 30) -> list[ModelCostSummary]:
        start_dt = datetime.now(timezone.utc) - timedelta(days=days)

        # Langfuse observations() returns a paginated list of generation records
        # `type="GENERATION"` filters to LLM call spans only
        observations = self._langfuse.observations(
            type        = "GENERATION",
            from_start_time = start_dt,
            limit       = 1000,   # fetch up to 1k generations; extend with pagination for larger volumes
        )

        # Aggregate: {model_id: {date: {cost, tokens}}}
        by_model: dict[str, dict[date, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"cost_usd": 0.0, "tokens": 0})
        )

        for obs in observations.data:
            model_id     = obs.model or "unknown"
            obs_date     = (obs.start_time or datetime.now(timezone.utc)).date()
            cost_usd     = obs.calculated_total_cost or 0.0
            total_tokens = (obs.usage.total_tokens or 0) if obs.usage else 0

            by_model[model_id][obs_date]["cost_usd"] += cost_usd
            by_model[model_id][obs_date]["tokens"]   += total_tokens

        # Build full date range (fill missing days with 0)
        all_dates = [start_dt.date() + timedelta(days=i) for i in range(days)]

        summaries: list[ModelCostSummary] = []
        for model_id, date_map in by_model.items():
            daily_series = [
                DailyCostPoint(date=d, cost_usd=date_map.get(d, {}).get("cost_usd", 0.0))
                for d in all_dates
            ]
            total_cost   = sum(p.cost_usd for p in daily_series)
            total_tokens = sum(v["tokens"] for v in date_map.values())

            summaries.append(ModelCostSummary(
                model_id       = model_id,
                total_cost_usd = round(total_cost, 4),
                daily_series   = daily_series,
                total_tokens   = total_tokens,
            ))

        # Sort by total cost descending — highest-spend models first
        return sorted(summaries, key=lambda s: s.total_cost_usd, reverse=True)
```

---

### FastAPI route

```python
# src/api/admin/routes/model_analytics.py
from __future__ import annotations
from typing     import Annotated
from fastapi    import APIRouter, Depends, Query
from src.api.admin.dependencies               import require_admin_role
from src.observability.cost.analytics_service import ModelCostAnalyticsService, ModelCostSummary

router     = APIRouter(prefix="/v1/models", tags=["Model Analytics"])
AdminClaims = Annotated[dict, Depends(require_admin_role)]


@router.get(
    "/cost-analytics",
    response_model = list[ModelCostSummary],
    summary        = "Per-model LLM cost totals and daily sparkline series (AC-4).",
)
async def get_model_cost_analytics(
    claims: AdminClaims,
    days:   int = Query(default=30, ge=1, le=90, description="Lookback window in days"),
) -> list[ModelCostSummary]:
    svc = ModelCostAnalyticsService()
    return await svc.get_model_cost_summary(days=days)
```

---

### Frontend: `useCostAnalytics` hook

```ts
// frontend/admin-portal/src/services/modelService.ts  (extend)

export interface DailyCostPoint {
  date:     string;
  cost_usd: number;
}

export interface ModelCostSummary {
  model_id:       string;
  total_cost_usd: number;
  daily_series:   DailyCostPoint[];
  total_tokens:   number;
}

export function useCostAnalytics(days = 30) {
  return useQuery({
    queryKey: ["model-cost-analytics", days],
    queryFn:  () =>
      api.get<ModelCostSummary[]>(`/v1/models/cost-analytics?days=${days}`).then((r) => r.data),
    staleTime: 5 * 60 * 1000,   // 5-minute cache — cost data doesn't need real-time refresh
  });
}
```

---

### `CostAnalyticsPanel`

```tsx
// frontend/admin-portal/src/components/models/CostAnalyticsPanel.tsx
import {
  LineChart, Line, ResponsiveContainer, Tooltip,
} from "recharts";
import { useCostAnalytics }  from "../../services/modelService";
import type { ModelCostSummary, DailyCostPoint } from "../../services/modelService";

export function CostAnalyticsPanel() {
  const { data: summaries, isLoading } = useCostAnalytics(30);

  return (
    <section aria-labelledby="cost-panel-heading" className="mt-8">
      <h2 id="cost-panel-heading" className="text-lg font-semibold mb-4">
        Cost Analytics — Last 30 Days
      </h2>

      {isLoading && <p role="status" aria-live="polite">Loading cost data…</p>}

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
              <th scope="col" className="px-4 py-2">Model</th>
              <th scope="col" className="px-4 py-2">30-day spend</th>
              <th scope="col" className="px-4 py-2">Total tokens</th>
              <th scope="col" className="px-4 py-2 w-40">Trend</th>
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
```

---

### Add analytics tab to `ModelListPage`

```tsx
// frontend/admin-portal/src/pages/models/ModelListPage.tsx  (extend — add below table)
import { CostAnalyticsPanel } from "../../components/models/CostAnalyticsPanel";

// Below the existing <table>:
<CostAnalyticsPanel />
```

## Acceptance Criteria

- [ ] `GET /v1/models/cost-analytics?days=30` returns one `ModelCostSummary` per model with `total_cost_usd` and `daily_series` of 30 `DailyCostPoint` objects (AC-4)
- [ ] Days with no LLM calls produce `DailyCostPoint(cost_usd=0.0)` entries — series length always equals `days` (AC-4)
- [ ] Results are sorted highest-spend-first (AC-4)
- [ ] `CostAnalyticsPanel` renders a row per model with: model_id, 30-day total formatted as `$N.NN`, token count, and a trend `LineChart` sparkline (AC-4)
- [ ] Sparkline has `role="img"` and `aria-label` describing the chart content (WCAG 2.1 AA)
- [ ] When all `cost_usd` values are 0 (no data), the sparkline renders "No data" text instead of an empty chart (AC-4)
- [ ] `days` query param is clamped to 1–90 by FastAPI's `Query(ge=1, le=90)` — prevents excessive Langfuse API calls

## Dependencies

- US-037 TASK-US037-01 — `LLMCostRecorder.record_llm_call()` writes generation records to Langfuse; those records are what this service reads
- TASK-US041-01 — `CostAnalyticsPanel` added below the existing model table in `ModelListPage`
- Langfuse `>= 2.0` Python SDK with `observations()` method

## Definition of Done

- [ ] `mypy --strict` passes on `analytics_service.py`; no `ruff` lint errors
- [ ] `pnpm build` succeeds; no TypeScript errors on Recharts imports
- [ ] pytest test: `get_model_cost_summary()` aggregates correctly from a mocked Langfuse response; empty result when no observations
