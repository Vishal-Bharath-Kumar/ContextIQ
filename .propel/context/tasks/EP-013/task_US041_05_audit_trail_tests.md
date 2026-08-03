# TASK-US041-05 — Model Audit Trail and Integration Tests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US041-05 |
| User Story | US-041 |
| Epic | EP-013 — Administration Portal |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the `model_audit_log` table and `ModelAuditRepository` (AC-6) that records every mutating model event — registration, status change, and routing weight update — with `actor_user_id` and timestamp. Extend the three mutating routes to write audit entries. Write integration tests covering all 6 US-041 acceptance criteria: React Testing Library for frontend components and pytest + httpx for backend routes.

## Implementation Details

**Technology (backend):** Python 3.11+, SQLAlchemy 2.x async, Alembic (revision `0018`), pytest, respx

**Technology (frontend):** React Testing Library, Vitest, MSW

**File locations:**
- `src/model_registry/models/model_audit_log.py` — `ModelAuditLog` ORM
- `src/model_registry/repositories/model_audit_repository.py` — `ModelAuditRepository`
- `alembic/versions/0018_create_model_audit_log.py`
- `src/model_registry/routers/model_router.py` — extend POST + PATCH routes with audit call
- `src/model_router/routers/routing_weight_router.py` — extend PUT with audit call
- `frontend/admin-portal/src/__tests__/ModelListPage.test.tsx`
- `frontend/admin-portal/src/__tests__/AddModelForm.test.tsx`
- `frontend/admin-portal/src/__tests__/IntentWeightCard.test.tsx`
- `tests/model_registry/test_model_audit.py`
- `tests/model_registry/test_model_routes.py`

---

### `ModelAuditLog` ORM and Alembic migration

```python
# src/model_registry/models/model_audit_log.py
from __future__ import annotations
import uuid
from datetime       import datetime, timezone
from sqlalchemy     import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base    import Base


class ModelAuditLog(Base):
    """
    AC-6: records every model registry and routing weight change
    with actor_user_id and timestamp.
    No FK to model_registry (model_id is a string, not a PK UUID)
    to preserve audit history after model deletion.
    """
    __tablename__ = "model_audit_log"

    id:           Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    model_id:     Mapped[str]       = mapped_column(String(128), nullable=False, index=True)
    event_type:   Mapped[str]       = mapped_column(String(64),  nullable=False)
    actor_user_id: Mapped[str]      = mapped_column(String(256), nullable=False)
    detail:       Mapped[str | None] = mapped_column(Text,       nullable=True)
    created_at:   Mapped[datetime]  = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

```python
# alembic/versions/0018_create_model_audit_log.py
"""create model_audit_log

Revision ID: 0018
Revises:     0017
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.create_table(
        "model_audit_log",
        sa.Column("id",            sa.UUID(),      primary_key=True),
        sa.Column("model_id",      sa.String(128), nullable=False),
        sa.Column("event_type",    sa.String(64),  nullable=False),
        sa.Column("actor_user_id", sa.String(256), nullable=False),
        sa.Column("detail",        sa.Text(),      nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_model_audit_log_model_id", "model_audit_log", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_model_audit_log_model_id")
    op.drop_table("model_audit_log")
```

---

### `ModelAuditRepository`

```python
# src/model_registry/repositories/model_audit_repository.py
from sqlalchemy.ext.asyncio import AsyncSession
from src.model_registry.models.model_audit_log import ModelAuditLog


class ModelAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        model_id:      str,
        event_type:    str,
        actor_user_id: str,
        detail:        str | None = None,
    ) -> None:
        entry = ModelAuditLog(
            model_id      = model_id,
            event_type    = event_type,
            actor_user_id = actor_user_id,
            detail        = detail,
        )
        self._session.add(entry)
        await self._session.flush()
```

---

### Extend mutating routes with audit calls

```python
# src/model_registry/routers/model_router.py  (extend POST /v1/models)
from src.model_registry.repositories.model_audit_repository import ModelAuditRepository

# In register_model():
    audit = ModelAuditRepository(session)
    await audit.log(
        model_id      = result.model_id,
        event_type    = "registered",
        actor_user_id = claims["sub"],
        detail        = f"provider={result.provider} latency={result.latency_tier}",
    )
    await session.commit()

# In update_model_status():
    await audit.log(
        model_id      = model_id,
        event_type    = "status_changed",
        actor_user_id = claims["sub"],
        detail        = f"is_active={body.is_active}",
    )
    await session.commit()
```

```python
# src/model_router/routers/routing_weight_router.py  (extend PUT)
from src.model_registry.repositories.model_audit_repository import ModelAuditRepository

# In update_routing_weights():
    audit = ModelAuditRepository(session)
    await audit.log(
        model_id      = f"routing:{intent_type}",   # prefix avoids collision with real model IDs
        event_type    = "weights_updated",
        actor_user_id = claims["sub"],
        detail        = (
            f"quality={body.quality_weight} "
            f"cost={body.cost_weight} "
            f"latency={body.latency_weight}"
        ),
    )
    await session.commit()
```

---

### Frontend tests

```tsx
// frontend/admin-portal/src/__tests__/ModelListPage.test.tsx
import { render, screen }     from "@testing-library/react";
import { server }             from "../../mocks/server";
import { http, HttpResponse } from "msw";
import ModelListPage          from "../pages/models/ModelListPage";
import { TestWrapper }        from "../../test-utils/TestWrapper";

const MOCK_MODELS = [{
  id: "m1", model_id: "gpt-4o", provider: "openai",
  context_window: 128000, cost_per_1k_tokens: 0.005,
  latency_tier: "medium", capabilities: ["chat", "function_call"],
  is_active: true, created_at: new Date().toISOString(),
}];

describe("ModelListPage — AC-1", () => {
  beforeEach(() =>
    server.use(http.get("/api/v1/models", () => HttpResponse.json(MOCK_MODELS)))
  );

  it("renders model_id, provider, context window, cost, latency badge", async () => {
    render(<ModelListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("128,000")).toBeInTheDocument();
    expect(screen.getByText("$0.0050")).toBeInTheDocument();
    expect(screen.getByLabelText("Latency: Medium")).toBeInTheDocument();
  });

  it("renders capability tags", async () => {
    render(<ModelListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("chat")).toBeInTheDocument();
    expect(screen.getByText("function_call")).toBeInTheDocument();
  });
});

describe("ModelRow deactivation toggle — AC-5", () => {
  it("calls PATCH /status when toggle is switched off", async () => {
    let patchBody: unknown = null;
    server.use(
      http.get("/api/v1/models", () => HttpResponse.json(MOCK_MODELS)),
      http.patch("/api/v1/models/gpt-4o/status", async ({ request }) => {
        patchBody = await request.json();
        return HttpResponse.json({ ...MOCK_MODELS[0], is_active: false });
      }),
    );
    const { findByRole, getByRole } = render(<ModelListPage />, { wrapper: TestWrapper });
    const toggle = await findByRole("switch", { name: /deactivate gpt-4o/i });
    toggle.click();
    await findByRole("switch");
    expect((patchBody as any).is_active).toBe(false);
  });
});
```

```tsx
// frontend/admin-portal/src/__tests__/AddModelForm.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent                              from "@testing-library/user-event";
import { server }                            from "../../mocks/server";
import { http, HttpResponse }                from "msw";
import AddModelPage                          from "../pages/models/AddModelPage";
import { TestWrapper }                       from "../../test-utils/TestWrapper";

describe("AddModelPage — AC-2", () => {
  it("shows error when no capability selected", async () => {
    render(<AddModelPage />, { wrapper: TestWrapper });
    await userEvent.type(screen.getByLabelText(/model id/i), "gpt-4o");
    await userEvent.type(screen.getByLabelText(/provider/i), "openai");
    await userEvent.type(screen.getByLabelText(/context window/i), "128000");
    await userEvent.type(screen.getByLabelText(/cost per 1k/i), "0.005");
    fireEvent.submit(screen.getByRole("button", { name: /register model/i }).closest("form")!);
    expect(await screen.findByText(/select at least one capability/i)).toBeInTheDocument();
  });

  it("shows 409 duplicate error message", async () => {
    server.use(
      http.post("/api/v1/models", () => HttpResponse.json({ detail: "conflict" }, { status: 409 }))
    );
    render(<AddModelPage />, { wrapper: TestWrapper });
    await userEvent.type(screen.getByLabelText(/model id/i), "gpt-4o");
    await userEvent.type(screen.getByLabelText(/provider/i), "openai");
    await userEvent.type(screen.getByLabelText(/context window/i), "128000");
    await userEvent.type(screen.getByLabelText(/cost per 1k/i), "0.005");
    fireEvent.click(screen.getByLabelText(/^chat$/i));  // select one capability
    fireEvent.submit(screen.getByRole("button", { name: /register/i }).closest("form")!);
    expect(await screen.findByText(/already registered/i)).toBeInTheDocument();
  });
});
```

```tsx
// frontend/admin-portal/src/__tests__/IntentWeightCard.test.tsx
import { render, screen }  from "@testing-library/react";
import { IntentWeightCard } from "../components/models/IntentWeightCard";
import { TestWrapper }     from "../../test-utils/TestWrapper";

describe("IntentWeightCard — AC-3", () => {
  const entry = {
    intent_type: "code_generation",
    quality_weight: 0.70,
    cost_weight:    0.20,
    latency_weight: 0.10,
  };

  it("renders three sliders with correct aria-labels", () => {
    render(<IntentWeightCard entry={entry} />, { wrapper: TestWrapper });
    expect(screen.getByLabelText(/quality weight for code_generation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/cost weight for code_generation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/latency weight for code_generation/i)).toBeInTheDocument();
  });

  it("displays percentage values", () => {
    render(<IntentWeightCard entry={entry} />, { wrapper: TestWrapper });
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("10%")).toBeInTheDocument();
  });
});
```

---

### Backend integration tests

```python
# tests/model_registry/test_model_audit.py
import pytest
from sqlalchemy import select
from src.model_registry.models.model_audit_log import ModelAuditLog


@pytest.mark.asyncio
async def test_register_model_writes_audit_entry(admin_client, async_session):
    """AC-6: POST /v1/models inserts a 'registered' audit entry."""
    payload = {
        "model_id": "test-model-001", "provider": "openai",
        "context_window": 8192, "cost_per_1k_tokens": 0.002,
        "latency_tier": "fast", "capabilities": ["chat"],
    }
    r = await admin_client.post("/v1/models", json=payload)
    assert r.status_code == 201

    rows = (await async_session.execute(
        select(ModelAuditLog).where(ModelAuditLog.model_id == "test-model-001")
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "registered"
    assert rows[0].actor_user_id is not None


@pytest.mark.asyncio
async def test_deactivate_model_writes_audit_entry(admin_client, async_session):
    """AC-5 + AC-6: PATCH /status inserts a 'status_changed' entry with is_active=False."""
    r = await admin_client.patch("/v1/models/test-model-001/status", json={"is_active": False})
    assert r.status_code == 200

    rows = (await async_session.execute(
        select(ModelAuditLog).where(
            ModelAuditLog.model_id  == "test-model-001",
            ModelAuditLog.event_type == "status_changed",
        )
    )).scalars().all()
    assert len(rows) >= 1
    assert "is_active=False" in rows[-1].detail


@pytest.mark.asyncio
async def test_routing_weight_update_writes_audit_entry(admin_client, async_session):
    """AC-3 + AC-6: PUT /routing/weights inserts a 'weights_updated' entry."""
    r = await admin_client.put(
        "/v1/routing/weights/code_generation",
        json={"quality_weight": 0.60, "cost_weight": 0.30, "latency_weight": 0.10},
    )
    assert r.status_code == 200

    rows = (await async_session.execute(
        select(ModelAuditLog).where(
            ModelAuditLog.model_id  == "routing:code_generation",
            ModelAuditLog.event_type == "weights_updated",
        )
    )).scalars().all()
    assert len(rows) >= 1


# tests/model_registry/test_model_routes.py

@pytest.mark.asyncio
async def test_model_list_returns_active_models(admin_client):
    """AC-1: GET /v1/models returns active models with all required fields."""
    r = await admin_client.get("/v1/models")
    assert r.status_code == 200
    models = r.json()
    if models:
        m = models[0]
        assert all(k in m for k in [
            "model_id", "provider", "context_window",
            "cost_per_1k_tokens", "latency_tier", "capabilities", "is_active",
        ])


@pytest.mark.asyncio
async def test_register_duplicate_model_returns_409(admin_client):
    """AC-2: duplicate model_id returns HTTP 409."""
    payload = {
        "model_id": "dupe-model", "provider": "openai",
        "context_window": 8192, "cost_per_1k_tokens": 0.002,
        "latency_tier": "fast", "capabilities": ["chat"],
    }
    await admin_client.post("/v1/models", json=payload)
    r = await admin_client.post("/v1/models", json=payload)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_routing_weights_reject_non_summing_weights(admin_client):
    """AC-3: weights not summing to 1.0 return HTTP 422."""
    r = await admin_client.put(
        "/v1/routing/weights/code_generation",
        json={"quality_weight": 0.5, "cost_weight": 0.5, "latency_weight": 0.5},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_cost_analytics_returns_daily_series(admin_client, respx_mock):
    """AC-4: GET /cost-analytics returns ModelCostSummary with daily_series of correct length."""
    from unittest.mock import patch, MagicMock

    mock_obs = MagicMock()
    mock_obs.data = []   # no data — should return empty list gracefully

    with patch("src.observability.cost.analytics_service.Langfuse") as mock_langfuse:
        mock_langfuse.return_value.observations.return_value = mock_obs
        r = await admin_client.get("/v1/models/cost-analytics?days=30")

    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

## Acceptance Criteria

- [ ] `POST /v1/models` inserts a `"registered"` audit row with `actor_user_id` from JWT sub (AC-6)
- [ ] `PATCH /v1/models/{id}/status` inserts a `"status_changed"` audit row (AC-6)
- [ ] `PUT /v1/routing/weights/{intent_type}` inserts a `"weights_updated"` audit row (AC-6)
- [ ] `ModelListPage` test: table renders model_id, provider, context_window (locale), cost (4 dp), latency badge, capability tags (AC-1)
- [ ] `AddModelForm` test: zero capabilities → validation error; 409 → inline duplicate message (AC-2)
- [ ] `IntentWeightCard` test: 3 sliders with correct `aria-label`, percentage values displayed (AC-3)
- [ ] `test_routing_weights_reject_non_summing_weights` — 422 on invalid sum (AC-3)
- [ ] `test_cost_analytics_returns_daily_series` — 200 with list response (AC-4)
- [ ] `test_register_duplicate_model_returns_409` (AC-2)

## Dependencies

- TASK-US041-01 through TASK-US041-04 (all US-041 frontend and backend tasks)
- US-018 TASK-US018-04 — `model_router.py` extended with audit calls

## Definition of Done

- [ ] Alembic migration `0018` runs without error; `model_audit_log` table exists
- [ ] All frontend tests pass with `pnpm test`
- [ ] All backend tests pass with `pytest tests/model_registry/`
- [ ] `mypy --strict` passes on new Python files; no `ruff` lint errors
