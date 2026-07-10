# TASK-US041-03 — Routing Weight Sliders per Intent Type

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US041-03 |
| User Story | US-041 |
| Epic | EP-013 — Administration Portal |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the routing weight editor (AC-3): a `routing_weight_overrides` PostgreSQL table and `GET`/`PUT /v1/routing/weights/{intent_type}` backend routes that allow admin-specified per-intent weights to override the static `INTENT_ROUTING_WEIGHT_TABLE` (US-019 TASK-US019-01). The `RoutingWeightsPage` frontend renders a Radix UI `Slider` for each of the three weights (`quality`, `cost`, `latency`) per intent type, with live re-normalisation so the three sliders always sum to 1.0.

## Implementation Details

**Technology (backend):** Python 3.11+, FastAPI, SQLAlchemy 2.x async, Alembic

**Technology (frontend):** React 18, TypeScript, TanStack Query v5 (`useQuery` / `useMutation`), Radix UI `Slider`, `@radix-ui/react-accordion`

**File locations:**
- `src/model_router/models/routing_weight_override.py` — `RoutingWeightOverride` ORM
- `src/model_router/repositories/routing_weight_repository.py` — `RoutingWeightRepository`
- `src/model_router/routers/routing_weight_router.py` — FastAPI routes
- `alembic/versions/0017_create_routing_weight_overrides.py`
- `frontend/admin-portal/src/pages/models/RoutingWeightsPage.tsx`
- `frontend/admin-portal/src/components/models/IntentWeightCard.tsx`
- `frontend/admin-portal/src/services/routingWeightService.ts`

---

### ORM + Alembic migration

```python
# src/model_router/models/routing_weight_override.py
from __future__ import annotations
import uuid
from datetime       import datetime, timezone
from sqlalchemy     import String, Float, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base    import Base


class RoutingWeightOverride(Base):
    __tablename__ = "routing_weight_overrides"
    __table_args__ = (
        UniqueConstraint("intent_type", name="uq_routing_weight_intent_type"),
    )

    id:             Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    intent_type:    Mapped[str]       = mapped_column(String(64), nullable=False, index=True)
    quality_weight: Mapped[float]     = mapped_column(Float, nullable=False)
    cost_weight:    Mapped[float]     = mapped_column(Float, nullable=False)
    latency_weight: Mapped[float]     = mapped_column(Float, nullable=False)
    updated_by:     Mapped[str]       = mapped_column(String(256), nullable=False)
    updated_at:     Mapped[datetime]  = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

```python
# alembic/versions/0017_create_routing_weight_overrides.py
"""create routing_weight_overrides

Revision ID: 0017
Revises:     0016
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.create_table(
        "routing_weight_overrides",
        sa.Column("id",             sa.UUID(),     primary_key=True),
        sa.Column("intent_type",    sa.String(64), nullable=False),
        sa.Column("quality_weight", sa.Float(),    nullable=False),
        sa.Column("cost_weight",    sa.Float(),    nullable=False),
        sa.Column("latency_weight", sa.Float(),    nullable=False),
        sa.Column("updated_by",     sa.String(256), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_routing_weight_overrides_intent_type", "routing_weight_overrides", ["intent_type"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_routing_weight_overrides_intent_type")
    op.drop_table("routing_weight_overrides")
```

---

### `RoutingWeightRepository`

```python
# src/model_router/repositories/routing_weight_repository.py
from __future__ import annotations
from sqlalchemy         import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio         import AsyncSession
from src.model_router.models.routing_weight_override import RoutingWeightOverride
from src.model_router.schemas.routing_weights        import RoutingWeights, INTENT_ROUTING_WEIGHT_TABLE


class RoutingWeightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, intent_type: str) -> RoutingWeights:
        """Return DB override if present, else the static preset."""
        row = (await self._session.execute(
            select(RoutingWeightOverride)
            .where(RoutingWeightOverride.intent_type == intent_type)
        )).scalar_one_or_none()

        if row:
            return RoutingWeights(
                quality_weight = row.quality_weight,
                cost_weight    = row.cost_weight,
                latency_weight = row.latency_weight,
            )
        return INTENT_ROUTING_WEIGHT_TABLE.get(
            intent_type,
            RoutingWeights(quality_weight=0.4, cost_weight=0.4, latency_weight=0.2),
        )

    async def upsert(
        self,
        intent_type:    str,
        weights:        RoutingWeights,
        actor_user_id:  str,
    ) -> None:
        """INSERT … ON CONFLICT (intent_type) DO UPDATE — idempotent."""
        stmt = (
            pg_insert(RoutingWeightOverride)
            .values(
                intent_type    = intent_type,
                quality_weight = weights.quality_weight,
                cost_weight    = weights.cost_weight,
                latency_weight = weights.latency_weight,
                updated_by     = actor_user_id,
            )
            .on_conflict_do_update(
                index_elements = ["intent_type"],
                set_            = {
                    "quality_weight": weights.quality_weight,
                    "cost_weight":    weights.cost_weight,
                    "latency_weight": weights.latency_weight,
                    "updated_by":     actor_user_id,
                },
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_all(self) -> list[dict]:
        """Return all 8 intent types with effective weights (override or static)."""
        from src.intents.constants import IntentType   # all 8 intent values
        return [
            {
                "intent_type": it,
                **(await self.get(it)).model_dump(),
            }
            for it in IntentType
        ]
```

---

### FastAPI routing weight routes

```python
# src/model_router/routers/routing_weight_router.py
from __future__ import annotations
import logging
from typing import Annotated

from fastapi             import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic            import BaseModel, ConfigDict, model_validator

from src.db.session      import get_async_session
from src.api.admin.dependencies     import require_admin_role
from src.model_router.repositories.routing_weight_repository import RoutingWeightRepository

router     = APIRouter(prefix="/v1/routing/weights", tags=["Routing Weights"])
AdminClaims = Annotated[dict, Depends(require_admin_role)]


class RoutingWeightResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_type:    str
    quality_weight: float
    cost_weight:    float
    latency_weight: float


class RoutingWeightUpdateRequest(BaseModel):
    quality_weight: float
    cost_weight:    float
    latency_weight: float

    @model_validator(mode="after")
    def sum_to_one(self) -> "RoutingWeightUpdateRequest":
        total = round(self.quality_weight + self.cost_weight + self.latency_weight, 6)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return self


@router.get(
    "",
    response_model = list[RoutingWeightResponse],
    summary        = "List effective routing weights for all intent types (AC-3).",
)
async def list_routing_weights(
    claims:  AdminClaims,
    session: AsyncSession = Depends(get_async_session),
) -> list[RoutingWeightResponse]:
    repo  = RoutingWeightRepository(session)
    items = await repo.list_all()
    return [RoutingWeightResponse(**item) for item in items]


@router.put(
    "/{intent_type}",
    response_model = RoutingWeightResponse,
    summary        = "Override routing weights for a specific intent type (AC-3).",
)
async def update_routing_weights(
    intent_type: str,
    body:        RoutingWeightUpdateRequest,
    claims:      AdminClaims,
    session:     AsyncSession = Depends(get_async_session),
) -> RoutingWeightResponse:
    from src.intents.constants import IntentType
    if intent_type not in [it.value for it in IntentType]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown intent type: {intent_type}")

    from src.model_router.schemas.routing_weights import RoutingWeights
    repo = RoutingWeightRepository(session)
    await repo.upsert(
        intent_type   = intent_type,
        weights       = RoutingWeights(
            quality_weight = body.quality_weight,
            cost_weight    = body.cost_weight,
            latency_weight = body.latency_weight,
        ),
        actor_user_id = claims["sub"],
    )
    await session.commit()
    return RoutingWeightResponse(
        intent_type    = intent_type,
        quality_weight = body.quality_weight,
        cost_weight    = body.cost_weight,
        latency_weight = body.latency_weight,
    )
```

---

### Frontend: `routingWeightService.ts`

```ts
// frontend/admin-portal/src/services/routingWeightService.ts
import axios                         from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface RoutingWeightEntry {
  intent_type:    string;
  quality_weight: number;
  cost_weight:    number;
  latency_weight: number;
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api" });
api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) cfg.headers.Authorization = `Bearer ${JSON.parse(raw).token}`;
  return cfg;
});

export const WEIGHT_KEYS = { all: ["routing-weights"] as const };

export function useRoutingWeights() {
  return useQuery({
    queryKey: WEIGHT_KEYS.all,
    queryFn:  () => api.get<RoutingWeightEntry[]>("/v1/routing/weights").then((r) => r.data),
  });
}

export function useUpdateRoutingWeights() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ intentType, weights }: {
      intentType: string;
      weights: { quality_weight: number; cost_weight: number; latency_weight: number };
    }) =>
      api.put(`/v1/routing/weights/${intentType}`, weights).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: WEIGHT_KEYS.all }),
  });
}
```

---

### `IntentWeightCard` — three sliders with live re-normalisation

```tsx
// frontend/admin-portal/src/components/models/IntentWeightCard.tsx
import { useState }              from "react";
import * as Slider               from "@radix-ui/react-slider";
import { useUpdateRoutingWeights } from "../../services/routingWeightService";
import type { RoutingWeightEntry } from "../../services/routingWeightService";

interface Props { entry: RoutingWeightEntry; }

type WeightKey = "quality_weight" | "cost_weight" | "latency_weight";
const WEIGHT_KEYS: { key: WeightKey; label: string; colour: string }[] = [
  { key: "quality_weight", label: "Quality", colour: "bg-blue-500"  },
  { key: "cost_weight",    label: "Cost",    colour: "bg-green-500" },
  { key: "latency_weight", label: "Latency", colour: "bg-amber-500" },
];

export function IntentWeightCard({ entry }: Props) {
  const [weights, setWeights] = useState({
    quality_weight: entry.quality_weight,
    cost_weight:    entry.cost_weight,
    latency_weight: entry.latency_weight,
  });
  const { mutate: save, isPending } = useUpdateRoutingWeights();

  /**
   * Re-normalise: when the user drags slider `key` to `newVal`,
   * distribute the remaining 1-newVal proportionally across the other two.
   */
  const handleChange = (key: WeightKey, newVal: number) => {
    const clamped  = Math.max(0.05, Math.min(0.90, newVal));
    const others   = WEIGHT_KEYS.map((w) => w.key).filter((k) => k !== key);
    const sumOther = others.reduce((s, k) => s + weights[k], 0) || 0.5;
    const scale    = (1 - clamped) / sumOther;

    setWeights({
      ...weights,
      [key]:      clamped,
      [others[0]]: Math.round(weights[others[0]] * scale * 100) / 100,
      [others[1]]: Math.round((1 - clamped - weights[others[0]] * scale) * 100) / 100,
    });
  };

  const handleSave = () =>
    save({ intentType: entry.intent_type, weights });

  return (
    <div className="border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium text-sm capitalize">
          {entry.intent_type.replace(/_/g, " ")}
        </h3>
        <button
          type="button"
          onClick={handleSave}
          disabled={isPending}
          className="btn-primary text-xs"
          aria-label={`Save routing weights for ${entry.intent_type}`}
        >
          {isPending ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="space-y-4">
        {WEIGHT_KEYS.map(({ key, label, colour }) => (
          <div key={key}>
            <div className="flex justify-between text-xs mb-1">
              <span>{label}</span>
              <span className="font-mono">{(weights[key] * 100).toFixed(0)}%</span>
            </div>
            <Slider.Root
              min={5}
              max={90}
              step={5}
              value={[Math.round(weights[key] * 100)]}
              onValueChange={([v]) => handleChange(key, v / 100)}
              aria-label={`${label} weight for ${entry.intent_type}`}
              className="relative flex items-center h-5 w-full"
            >
              <Slider.Track className="bg-gray-200 relative grow rounded-full h-1.5">
                <Slider.Range className={`absolute rounded-full h-full ${colour}`} />
              </Slider.Track>
              <Slider.Thumb
                className="block w-4 h-4 rounded-full bg-white border-2 border-gray-400 shadow
                  focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </Slider.Root>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

### `RoutingWeightsPage`

```tsx
// frontend/admin-portal/src/pages/models/RoutingWeightsPage.tsx
import { useRoutingWeights } from "../../services/routingWeightService";
import { IntentWeightCard }  from "../../components/models/IntentWeightCard";

export default function RoutingWeightsPage() {
  const { data: entries, isLoading } = useRoutingWeights();

  return (
    <main aria-labelledby="weights-heading">
      <h1 id="weights-heading" className="text-2xl font-semibold mb-2">
        Model Routing Weights
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        Adjust quality, cost, and latency priorities per intent type.
        The three values always sum to 100%.
      </p>

      {isLoading && <p role="status" aria-live="polite">Loading routing weights…</p>}

      {entries && (
        <div className="grid grid-cols-2 gap-4">
          {entries.map((e) => (
            <IntentWeightCard key={e.intent_type} entry={e} />
          ))}
        </div>
      )}
    </main>
  );
}
```

## Acceptance Criteria

- [ ] `GET /v1/routing/weights` returns all 8 intent types with their effective weights (DB override or static preset) (AC-3)
- [ ] `PUT /v1/routing/weights/{intent_type}` with weights that don't sum to 1.0 returns HTTP 422 (AC-3)
- [ ] Saved overrides are stored in `routing_weight_overrides` via `INSERT … ON CONFLICT DO UPDATE` (AC-3)
- [ ] `RoutingWeightsPage` shows all 8 intent types each with 3 sliders labeled Quality, Cost, Latency (AC-3)
- [ ] Dragging one slider re-normalises the other two so the displayed total remains 100% (AC-3)
- [ ] Slider minimum is 5% (0.05) and maximum is 90% (0.90) — prevents degenerate 0/0/1 configurations
- [ ] Each `Slider.Thumb` has `aria-label` including the weight name and intent type (WCAG 2.1 AA)
- [ ] Alembic migration `0017` creates the `routing_weight_overrides` table

## Dependencies

- TASK-US041-01 — `RoutingWeightsPage` registered in `ADMIN_ROUTES` via `/models/weights`
- US-019 TASK-US019-01 — `RoutingWeights`, `INTENT_ROUTING_WEIGHT_TABLE`, `IntentType` used by backend

## Definition of Done

- [ ] `pnpm build` succeeds; no TypeScript errors
- [ ] `mypy --strict` on `routing_weight_router.py` and `routing_weight_repository.py`
- [ ] Tests: weights-not-summing-to-1 returns 422; upsert idempotency; slider re-normalisation logic
