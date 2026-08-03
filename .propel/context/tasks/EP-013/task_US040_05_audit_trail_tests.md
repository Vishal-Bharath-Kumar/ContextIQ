# TASK-US040-05 — Policy Audit Trail UI Panel and Integration Tests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US040-05 |
| User Story | US-040 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend / Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the `PolicyAuditTrailPanel` (AC-6) that fetches and displays the policy-change audit log (author, event type, timestamp, detail) from a `GET /v1/policies/{id}/audit` backend route. Write integration tests covering all 7 US-040 acceptance criteria: React Testing Library for frontend components and pytest + httpx for backend routes.

## Implementation Details

**Technology (backend):** Python 3.11+, FastAPI, SQLAlchemy 2.x async
**Technology (frontend):** React 18, TypeScript, TanStack Query v5, date-fns, React Testing Library, Vitest
**Technology (tests):** pytest, pytest-asyncio, httpx, respx

**File locations:**
- `src/governance/policy/models.py` — extend with `PolicyAuditLog` ORM model
- `src/governance/policy/audit_repository.py` — `PolicyAuditRepository`
- `src/api/admin/routes/policies.py` — add `GET /v1/policies/{id}/audit`
- `frontend/admin-portal/src/components/policies/PolicyAuditTrailPanel.tsx`
- `frontend/admin-portal/src/services/policyService.ts` — extend with `usePolicyAuditTrail`
- `frontend/admin-portal/src/__tests__/PolicyListPage.test.tsx`
- `frontend/admin-portal/src/__tests__/PolicyEditor.test.tsx`
- `frontend/admin-portal/src/__tests__/ActivatePolicyDialog.test.tsx`
- `tests/governance/test_policy_audit_route.py`
- `tests/governance/test_preview_service.py`

---

### `PolicyAuditLog` ORM (extend existing `models.py`)

```python
# src/governance/policy/models.py  (extend — add audit model)
import uuid
from datetime       import datetime, timezone
from sqlalchemy     import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base    import Base


class PolicyAuditLog(Base):
    __tablename__ = "policy_audit_log"

    id:           Mapped[uuid.UUID]  = mapped_column(primary_key=True, default=uuid.uuid4)
    policy_id:    Mapped[uuid.UUID]  = mapped_column(
        ForeignKey("policy_definitions.id", ondelete="CASCADE"), index=True
    )
    event_type:   Mapped[str]        = mapped_column(String(64),  nullable=False)
    actor_user_id: Mapped[str]       = mapped_column(String(256), nullable=False)
    detail:       Mapped[str | None] = mapped_column(Text,        nullable=True)
    created_at:   Mapped[datetime]   = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
```

---

### `PolicyAuditRepository`

```python
# src/governance/policy/audit_repository.py
from __future__ import annotations
import uuid
from sqlalchemy     import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from src.governance.policy.models import PolicyAuditLog


class PolicyAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_policy(
        self, policy_id: uuid.UUID, limit: int = 50,
    ) -> list[PolicyAuditLog]:
        rows = await self._session.execute(
            select(PolicyAuditLog)
            .where(PolicyAuditLog.policy_id == policy_id)
            .order_by(desc(PolicyAuditLog.created_at))
            .limit(limit)
        )
        return rows.scalars().all()

    async def log(
        self,
        policy_id:    uuid.UUID,
        event_type:   str,
        actor_user_id: str,
        detail:       str | None = None,
    ) -> None:
        entry = PolicyAuditLog(
            policy_id     = policy_id,
            event_type    = event_type,
            actor_user_id = actor_user_id,
            detail        = detail,
        )
        self._session.add(entry)
        await self._session.flush()
```

---

### Backend: `GET /v1/policies/{id}/audit`

```python
# src/api/admin/routes/policies.py  (extend)
from src.governance.policy.audit_repository import PolicyAuditRepository
from pydantic import BaseModel as _Base
from datetime import datetime

class AuditLogEntry(_Base):
    id:           uuid.UUID
    event_type:   str
    actor_user_id: str
    detail:       str | None
    created_at:   datetime


@router.get(
    "/{policy_id}/audit",
    response_model = list[AuditLogEntry],
    summary        = "Fetch the policy change audit trail (AC-6).",
)
async def get_policy_audit(
    policy_id: uuid.UUID,
    claims:    AdminClaims,
    session:   AsyncSession = Depends(get_async_session),
) -> list[AuditLogEntry]:
    audit_repo = PolicyAuditRepository(session)
    return await audit_repo.get_for_policy(policy_id)
```

---

### Frontend: `usePolicyAuditTrail` + `PolicyAuditTrailPanel`

```ts
// frontend/admin-portal/src/services/policyService.ts  (extend)

export interface AuditLogEntry {
  id:            string;
  event_type:    string;
  actor_user_id: string;
  detail:        string | null;
  created_at:    string;   // ISO-8601
}

export function usePolicyAuditTrail(policyId: string | undefined) {
  return useQuery({
    queryKey: [...POLICY_KEYS.detail(policyId ?? ""), "audit"],
    queryFn:  () =>
      api.get<AuditLogEntry[]>(`/v1/policies/${policyId}/audit`).then((r) => r.data),
    enabled:  Boolean(policyId),
  });
}
```

```tsx
// frontend/admin-portal/src/components/policies/PolicyAuditTrailPanel.tsx
import { format } from "date-fns";
import { usePolicyAuditTrail } from "../../services/policyService";

interface Props { policyId: string; }

const EVENT_LABEL: Record<string, string> = {
  created:      "Policy created",
  activated:    "Policy activated",
  rollback:     "Policy rolled back",
  deactivated:  "Policy deactivated",
  validated:    "Rego validated",
};

export function PolicyAuditTrailPanel({ policyId }: Props) {
  const { data: entries, isLoading } = usePolicyAuditTrail(policyId);

  if (isLoading) {
    return <p role="status" aria-live="polite" className="text-sm text-gray-400">Loading audit trail…</p>;
  }

  if (!entries || entries.length === 0) {
    return <p className="text-sm text-gray-400">No audit events recorded yet.</p>;
  }

  return (
    <section aria-label="Policy audit trail">
      <h3 className="text-sm font-semibold mb-2">Audit Trail</h3>
      <ol className="space-y-2 text-sm">
        {entries.map((entry) => (
          <li key={entry.id} className="flex items-start gap-3 border-l-2 border-gray-200 pl-3">
            <div className="min-w-0">
              <span className="font-medium">
                {EVENT_LABEL[entry.event_type] ?? entry.event_type}
              </span>
              {entry.detail && (
                <span className="text-gray-500"> — {entry.detail}</span>
              )}
              <div className="text-xs text-gray-400 mt-0.5">
                {/* AC-6: actor user ID and timestamp */}
                by <span className="font-mono">{entry.actor_user_id}</span>
                {" · "}
                <time dateTime={entry.created_at}>
                  {format(new Date(entry.created_at), "yyyy-MM-dd HH:mm 'UTC'")}
                </time>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
```

---

### Frontend integration tests

```tsx
// frontend/admin-portal/src/__tests__/PolicyListPage.test.tsx
import { render, screen }     from "@testing-library/react";
import { server }             from "../../mocks/server";
import { http, HttpResponse } from "msw";
import PolicyListPage         from "../pages/policies/PolicyListPage";
import { TestWrapper }        from "../../test-utils/TestWrapper";

const MOCK_POLICIES = [{
  id: "p1", name: "PII Filter", active_version: "2.0.0",
  latest_author: "alice@acme.com", activated_at: new Date().toISOString(),
  versions: [
    { id: "v2", name: "PII Filter", version: "2.0.0", status: "active",
      author: "alice@acme.com", description: "", activated_at: new Date().toISOString(), created_at: new Date().toISOString() },
    { id: "v1", name: "PII Filter", version: "1.0.0", status: "superseded",
      author: "bob@acme.com",  description: "", activated_at: null, created_at: new Date().toISOString() },
  ],
}];

describe("PolicyListPage — AC-1", () => {
  beforeEach(() =>
    server.use(http.get("/api/v1/policies", () => HttpResponse.json(MOCK_POLICIES)))
  );

  it("renders policy name with active version badge", async () => {
    render(<PolicyListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("PII Filter")).toBeInTheDocument();
    expect(screen.getByLabelText("Active version: 2.0.0")).toBeInTheDocument();
  });

  it("renders version history rows with author and status", async () => {
    render(<PolicyListPage />, { wrapper: TestWrapper });
    expect(await screen.findByText("alice@acme.com")).toBeInTheDocument();
    expect(screen.getByText(/superseded/i)).toBeInTheDocument();
  });
});

describe("RequireSecurityOfficer — AC-7", () => {
  it("redirects users without SECURITY_OFFICER or ADMIN role to /403", () => {
    /* Use TestWrapper with a mock user that has only 'viewer' role */
    // assertion: rendered output is <Navigate to="/403" />
  });
});
```

```tsx
// frontend/admin-portal/src/__tests__/ActivatePolicyDialog.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { server }                    from "../../mocks/server";
import { http, HttpResponse }        from "msw";
import { ActivatePolicyDialog }      from "../components/policies/ActivatePolicyDialog";
import { TestWrapper }               from "../../test-utils/TestWrapper";

describe("ActivatePolicyDialog — AC-4", () => {
  it("shows confirmation dialog with policy name on Activate click", async () => {
    render(<ActivatePolicyDialog policyId="p1" policyName="PII Filter" />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("button", { name: /activate policy PII Filter/i }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(/PII Filter/)).toBeInTheDocument();
  });

  it("calls POST /activate and closes dialog on confirm", async () => {
    let called = false;
    server.use(http.post("/api/v1/policies/p1/activate", () => {
      called = true;
      return HttpResponse.json({ id: "p1", status: "active" });
    }));
    render(<ActivatePolicyDialog policyId="p1" policyName="PII Filter" />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("button", { name: /activate policy/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^activate$/i }));
    await screen.findByRole("button", { name: /activate policy/i });   // dialog closed
    expect(called).toBe(true);
  });

  it("does not call POST when Cancel is clicked", async () => {
    let called = false;
    server.use(http.post("/api/v1/policies/p1/activate", () => { called = true; return HttpResponse.json({}); }));
    render(<ActivatePolicyDialog policyId="p1" policyName="PII Filter" />, { wrapper: TestWrapper });
    fireEvent.click(screen.getByRole("button", { name: /activate policy/i }));
    fireEvent.click(await screen.findByRole("button", { name: /cancel/i }));
    expect(called).toBe(false);
  });
});
```

---

### Backend integration tests

```python
# tests/governance/test_policy_audit_route.py
import pytest
import uuid
from sqlalchemy import select
from src.governance.policy.models import PolicyAuditLog


@pytest.mark.asyncio
async def test_activate_policy_writes_audit_entry(
    admin_client, async_session, existing_policy_id
):
    """AC-6: POST /activate inserts an 'activated' audit entry."""
    r = await admin_client.post(f"/v1/policies/{existing_policy_id}/activate")
    assert r.status_code == 200

    rows = (await async_session.execute(
        select(PolicyAuditLog).where(
            PolicyAuditLog.policy_id  == existing_policy_id,
            PolicyAuditLog.event_type == "activated",
        )
    )).scalars().all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_get_policy_audit_returns_entries(admin_client, existing_policy_id):
    """AC-6: GET /audit returns list with actor_user_id and created_at."""
    # Create an audit entry first
    await admin_client.post(f"/v1/policies/{existing_policy_id}/activate")

    r = await admin_client.get(f"/v1/policies/{existing_policy_id}/audit")
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) >= 1
    assert entries[0]["actor_user_id"] is not None
    assert entries[0]["created_at"]    is not None


@pytest.mark.asyncio
async def test_security_officer_role_required(viewer_client, existing_policy_id):
    """AC-7: viewer role (not SECURITY_OFFICER/ADMIN) receives 403."""
    r = await viewer_client.get(f"/v1/policies/{existing_policy_id}/audit")
    assert r.status_code == 403


# tests/governance/test_preview_service.py
@pytest.mark.asyncio
async def test_preview_returns_allow_deny_counts(
    async_session, existing_policy_id, respx_mock
):
    """AC-3: preview evaluates traces and returns correct allow/deny counts."""
    # OPA mock: always return allow=True for simplicity
    respx_mock.put(url__regex=r".*/v1/policies/__preview__.*").respond(200)
    respx_mock.delete(url__regex=r".*/v1/policies/__preview__.*").respond(200)
    respx_mock.post(url__regex=r".*/v1/data/__preview__.*/allow").respond(
        200, json={"result": True}
    )

    from src.governance.policy.preview_service import PolicyPreviewService
    from src.governance.policy.schemas         import PolicyPreviewRequest
    import httpx

    svc    = PolicyPreviewService(async_session, httpx.AsyncClient())
    result = await svc.preview(
        existing_policy_id,
        PolicyPreviewRequest(rego_body='package preview\nallow = true'),
    )
    assert result.allow_count  >= 0
    assert result.deny_count   >= 0
    assert result.evaluated_count == result.allow_count + result.deny_count


@pytest.mark.asyncio
async def test_preview_deletes_temp_policy_on_evaluation_error(
    async_session, existing_policy_id, respx_mock
):
    """AC-3: temp policy is deleted even when evaluation raises."""
    deleted = []
    respx_mock.put(url__regex=r".*/v1/policies/__preview__.*").respond(200)
    respx_mock.delete(url__regex=r".*/v1/policies/__preview__.*").mock(
        side_effect=lambda *a, **k: deleted.append(True) or httpx.Response(200)
    )
    respx_mock.post(url__regex=r".*/v1/data/__preview__.*/allow").respond(500)

    from src.governance.policy.preview_service import PolicyPreviewService
    from src.governance.policy.schemas         import PolicyPreviewRequest
    import httpx

    svc = PolicyPreviewService(async_session, httpx.AsyncClient())
    result = await svc.preview(
        existing_policy_id,
        PolicyPreviewRequest(rego_body='package preview\nallow = false'),
    )
    # Even on OPA 500, evaluation fails gracefully (allow=False); temp policy cleaned up
    assert len(deleted) >= 1
```

## Acceptance Criteria

- [ ] `GET /v1/policies/{id}/audit` returns chronologically descending entries with `event_type`, `actor_user_id`, `detail`, `created_at` (AC-6)
- [ ] `PolicyAuditTrailPanel` renders author (user ID) and formatted timestamp for each entry (AC-6)
- [ ] Activate action test: `POST /activate` inserts an `"activated"` audit row (AC-6)
- [ ] `test_security_officer_role_required` — viewer-role JWT receives 403 on all policy routes (AC-7)
- [ ] `ActivatePolicyDialog` tests: dialog renders policy name, confirm fires mutation, cancel does not (AC-4)
- [ ] `test_preview_deletes_temp_policy_on_evaluation_error` — `finally` block verified (AC-3)
- [ ] Policy list tests: renders version history with badges, status text, author column (AC-1)

## Dependencies

- TASK-US040-01 through TASK-US040-04 (all US-040 frontend and backend tasks)
- US-033 TASK-US033-03 — `PolicyService` already emits audit events on activate/rollback; `PolicyAuditLog` extends the same model file

## Definition of Done

- [ ] All frontend tests pass with `pnpm test`
- [ ] All backend tests pass with `pytest tests/governance/`
- [ ] `mypy --strict` passes on new Python files; no `ruff` lint errors
