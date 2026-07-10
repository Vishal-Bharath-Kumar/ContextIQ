# TASK-US040-04 — Preview Impact: Backend Simulation Route and Frontend Statistics Panel

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US040-04 |
| User Story | US-040 |
| Epic | EP-013 — Administration Portal |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the "Preview Impact" feature (AC-3): a `POST /v1/policies/{id}/preview` backend endpoint that runs the unsaved Rego body against the last 100 execution traces stored in the `execution_traces` table (US-034) and returns projected `allow_count`, `deny_count`, and `affected_request_ids`. The frontend `PreviewImpactPanel` component shows the result inline in a collapsible panel — no page navigation required.

## Implementation Details

**Technology (backend):** Python 3.11+, FastAPI, SQLAlchemy 2.x async, httpx (OPA evaluation)

**Technology (frontend):** React 18, TypeScript, TanStack Query v5 (`useMutation`), Radix UI `Collapsible`

**File locations:**
- `src/api/admin/routes/policies.py` — extend with `POST /v1/policies/{id}/preview`
- `src/governance/policy/preview_service.py` — `PolicyPreviewService`
- `frontend/admin-portal/src/components/policies/PreviewImpactPanel.tsx`
- `frontend/admin-portal/src/services/policyService.ts` — extend with `usePreviewPolicy`

---

### Pydantic schemas

```python
# src/governance/policy/schemas.py  (extend — add preview types)
from pydantic import BaseModel, ConfigDict

class PolicyPreviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    rego_body: str   # the draft Rego to evaluate (not persisted)


class PolicyPreviewResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluated_count: int       # number of traces evaluated (≤ 100)
    allow_count:     int       # traces that would be allowed
    deny_count:      int       # traces that would be denied
    allow_pct:       float     # allow_count / evaluated_count * 100
    deny_pct:        float     # deny_count  / evaluated_count * 100
    affected_request_ids: list[str]  # request_ids of traces that would be denied
```

---

### `PolicyPreviewService`

```python
# src/governance/policy/preview_service.py
from __future__ import annotations
import uuid
import logging
from typing import Any
import httpx
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.governance.policy.schemas    import PolicyPreviewRequest, PolicyPreviewResult
from src.traces.models                import TraceRecord              # EP-011 US-034
from src.config                       import settings

logger = logging.getLogger(__name__)

_PREVIEW_TRACE_LIMIT = 100
_TEMP_POLICY_PREFIX  = "__preview__"


class PolicyPreviewService:
    """
    Simulates the effect of a draft Rego policy against the last N execution traces
    by pushing it to OPA under a temporary policy name and evaluating each trace's
    ChunkAuthzInput, then deleting the temporary policy.
    """

    def __init__(self, session: AsyncSession, opa_client: httpx.AsyncClient) -> None:
        self._session   = session
        self._opa       = opa_client
        self._opa_base  = settings.opa_base_url

    async def preview(
        self, policy_id: uuid.UUID, request: PolicyPreviewRequest,
    ) -> PolicyPreviewResult:
        traces     = await self._load_recent_traces()
        temp_name  = f"{_TEMP_POLICY_PREFIX}{policy_id.hex}"

        await self._push_temp_policy(temp_name, request.rego_body)
        try:
            results = await self._evaluate_traces(temp_name, traces)
        finally:
            await self._delete_temp_policy(temp_name)

        allow = sum(1 for r in results if r)
        deny  = len(results) - allow
        n     = len(results) or 1   # guard division-by-zero

        return PolicyPreviewResult(
            evaluated_count      = len(results),
            allow_count          = allow,
            deny_count           = deny,
            allow_pct            = round(allow / n * 100, 1),
            deny_pct             = round(deny  / n * 100, 1),
            affected_request_ids = [
                str(traces[i]["request_id"])
                for i, r in enumerate(results)
                if not r
            ],
        )

    async def _load_recent_traces(self) -> list[dict]:
        """Load the last 100 execution trace index rows for evaluation input."""
        rows = (await self._session.execute(
            select(TraceRecord)
            .order_by(desc(TraceRecord.timestamp))
            .limit(_PREVIEW_TRACE_LIMIT)
        )).scalars().all()

        return [
            {
                "request_id":  row.request_id,
                "user_id":     row.user_id,
                "tenant_id":   row.tenant_id,
                "intent_type": row.intent_type,
                "chunk_id":    None,   # not available at trace level; OPA policy must handle None
            }
            for row in rows
        ]

    async def _push_temp_policy(self, name: str, rego_body: str) -> None:
        resp = await self._opa.put(
            f"{self._opa_base}/v1/policies/{name}",
            content = rego_body.encode(),
            headers = {"Content-Type": "text/plain"},
        )
        resp.raise_for_status()

    async def _delete_temp_policy(self, name: str) -> None:
        try:
            await self._opa.delete(f"{self._opa_base}/v1/policies/{name}")
        except Exception:
            logger.warning("Failed to clean up temporary preview policy %s", name)

    async def _evaluate_traces(
        self, policy_name: str, traces: list[dict],
    ) -> list[bool]:
        """Evaluate each trace against the temporary policy; returns list of allow booleans."""
        results: list[bool] = []
        for trace in traces:
            try:
                resp = await self._opa.post(
                    f"{self._opa_base}/v1/data/{policy_name}/allow",
                    json={"input": trace},
                )
                allowed = resp.json().get("result", False) is True
            except Exception:
                allowed = False   # treat OPA call failure as deny
            results.append(allowed)
        return results
```

---

### Backend route

```python
# src/api/admin/routes/policies.py  (extend — add preview route)
from src.governance.policy.preview_service import PolicyPreviewService
from src.governance.policy.schemas         import PolicyPreviewRequest, PolicyPreviewResult

@router.post(
    "/{policy_id}/preview",
    response_model = PolicyPreviewResult,
    summary        = "Simulate a draft policy against the last 100 execution traces (AC-3).",
)
async def preview_policy(
    policy_id: uuid.UUID,
    body:      PolicyPreviewRequest,
    claims:    AdminClaims,
    session:   AsyncSession = Depends(get_async_session),
) -> PolicyPreviewResult:
    import httpx
    svc = PolicyPreviewService(
        session    = session,
        opa_client = httpx.AsyncClient(),
    )
    return await svc.preview(policy_id, body)
```

---

### Frontend: `usePreviewPolicy` mutation

```ts
// frontend/admin-portal/src/services/policyService.ts  (extend)

export interface PolicyPreviewResult {
  evaluated_count:      number;
  allow_count:          number;
  deny_count:           number;
  allow_pct:            number;
  deny_pct:             number;
  affected_request_ids: string[];
}

export function usePreviewPolicy() {
  return useMutation({
    mutationFn: ({ policyId, regoBody }: { policyId: string; regoBody: string }) =>
      api
        .post<PolicyPreviewResult>(`/v1/policies/${policyId}/preview`, {
          rego_body: regoBody,
        })
        .then((r) => r.data),
  });
}
```

---

### `PreviewImpactPanel`

```tsx
// frontend/admin-portal/src/components/policies/PreviewImpactPanel.tsx
import * as Collapsible                  from "@radix-ui/react-collapsible";
import { ChevronDownIcon, ChevronUpIcon } from "@radix-ui/react-icons";
import { useState }                      from "react";
import { usePreviewPolicy }              from "../../services/policyService";
import type { PolicyPreviewResult }      from "../../services/policyService";

interface Props {
  policyId: string;
  regoBody: string;   // current editor content passed in from PolicyDetailPage
}

export function PreviewImpactPanel({ policyId, regoBody }: Props) {
  const [open, setOpen]                   = useState(false);
  const { mutate: preview, isPending, data: result } = usePreviewPolicy();

  const handlePreview = () => {
    setOpen(true);
    preview({ policyId, regoBody });
  };

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen}>
      <Collapsible.Trigger asChild>
        <button
          type="button"
          className="btn-secondary flex items-center gap-1"
          onClick={handlePreview}
          aria-expanded={open}
          aria-controls="preview-impact-content"
          aria-label="Preview impact of this policy on recent requests"
        >
          Preview Impact
          {open ? <ChevronUpIcon aria-hidden="true" /> : <ChevronDownIcon aria-hidden="true" />}
        </button>
      </Collapsible.Trigger>

      <Collapsible.Content id="preview-impact-content">
        <div
          className="mt-3 p-4 border rounded-lg bg-gray-50"
          aria-live="polite"
          role="region"
          aria-label="Preview impact results"
        >
          {isPending && (
            <p role="status">Simulating against last {100} requests…</p>
          )}

          {result && !isPending && (
            <PreviewStats result={result} />
          )}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

function PreviewStats({ result }: { result: PolicyPreviewResult }) {
  return (
    <div>
      <p className="text-sm mb-3">
        Evaluated <strong>{result.evaluated_count}</strong> recent requests:
      </p>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-green-50 rounded p-3 text-center">
          <div className="text-2xl font-bold text-green-700">{result.allow_count}</div>
          <div className="text-xs text-green-600">Would Allow ({result.allow_pct}%)</div>
        </div>
        <div className="bg-red-50 rounded p-3 text-center">
          <div className="text-2xl font-bold text-red-700">{result.deny_count}</div>
          <div className="text-xs text-red-600">Would Deny ({result.deny_pct}%)</div>
        </div>
      </div>

      {result.affected_request_ids.length > 0 && (
        <details>
          <summary className="text-sm font-medium text-gray-700 cursor-pointer mb-1">
            Affected request IDs ({result.affected_request_ids.length})
          </summary>
          <ul className="text-xs font-mono space-y-0.5 max-h-40 overflow-y-auto">
            {result.affected_request_ids.map((id) => (
              <li key={id} className="text-gray-500">{id}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
```

## Acceptance Criteria

- [ ] `POST /v1/policies/{id}/preview` evaluates the draft Rego against ≤ 100 most recent `TraceRecord` rows (AC-3)
- [ ] Response contains `allow_count`, `deny_count`, `allow_pct`, `deny_pct`, and `affected_request_ids` (AC-3)
- [ ] Temporary OPA policy is always deleted in the `finally` block — no orphaned preview policies in OPA (AC-3)
- [ ] Division-by-zero guard when `evaluated_count == 0` (no traces yet) — returns 0 / 0 % gracefully
- [ ] "Preview Impact" button is `aria-expanded="true"` when the panel is open (WCAG 2.1 AA)
- [ ] While preview is pending, `role="status"` message is rendered; on completion, `role="region"` with `aria-live="polite"` announces the results (AC-7)
- [ ] `affected_request_ids` list is inside a `<details>` element — collapsed by default to avoid overwhelming the UI

## Dependencies

- US-034 TASK-US034-03 — `TraceRecord` ORM used by `_load_recent_traces()`
- US-033 TASK-US033-04 — Policy routes router where the preview route is added
- TASK-US040-02 — `PolicyDetailPage` passes `regoBody` state to `PreviewImpactPanel`

## Definition of Done

- [ ] `mypy --strict` passes on `preview_service.py`; no `ruff` lint errors
- [ ] `pnpm build` succeeds; no TypeScript errors
- [ ] pytest tests: `preview()` returns correct allow/deny counts; temp policy is deleted even when evaluation raises
