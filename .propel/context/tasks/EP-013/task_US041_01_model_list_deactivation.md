# TASK-US041-01 — Model List Page and Deactivation Toggle

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US041-01 |
| User Story | US-041 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the model list page (AC-1) that renders all registered AI models with their provider, context window, cost per 1k tokens, latency tier, capability tags, and active/inactive status. Add a deactivation toggle (AC-5) that calls a new `PATCH /v1/models/{id}/status` backend route — immediately removing the model from routing candidates when deactivated. Register the model routes in `ADMIN_ROUTES` (from TASK-US039-01).

## Implementation Details

**Technology (frontend):** React 18, TypeScript, TanStack Query v5, Radix UI `Switch`, Tailwind CSS

**Technology (backend):** Python 3.11+, FastAPI, SQLAlchemy 2.x async — extends `model_router.py` from TASK-US018-04

**File locations:**
- `frontend/admin-portal/src/pages/models/ModelListPage.tsx`
- `frontend/admin-portal/src/components/models/ModelRow.tsx`
- `frontend/admin-portal/src/components/models/LatencyBadge.tsx`
- `frontend/admin-portal/src/components/models/CapabilityTagList.tsx`
- `frontend/admin-portal/src/services/modelService.ts`
- `frontend/admin-portal/src/routes/index.tsx` — extend with model routes
- `src/model_registry/routers/model_router.py` — extend with PATCH status route

---

### Backend: `PATCH /v1/models/{model_id}/status`

```python
# src/model_registry/routers/model_router.py  (extend existing router)
from pydantic        import BaseModel as _Base
from src.api.admin.dependencies import require_admin_role

class ModelStatusUpdate(_Base):
    is_active: bool

@router.patch(
    "/{model_id}/status",
    response_model = ModelDefinition,
    summary        = "Activate or deactivate a model (AC-5). Deactivation takes effect immediately.",
    dependencies   = [Depends(require_admin_role)],
)
async def update_model_status(
    model_id: str,
    body:     ModelStatusUpdate,
    service:  ModelRegistryService = Depends(get_model_registry_service),
) -> ModelDefinition:
    """
    Sets is_active on the model record and invalidates the Redis cache so that
    the Dynamic Model Router sees the change on its next lookup (<30 s, AC-5).
    """
    return await service.set_active(model_id, body.is_active)
```

---

### TypeScript interfaces and TanStack Query hooks

```ts
// frontend/admin-portal/src/services/modelService.ts
import axios                          from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export type LatencyTier      = "fast" | "medium" | "slow";
export type ModelCapability  =
  | "chat" | "completion" | "embedding"
  | "code" | "summarization" | "vision" | "function_call";

export interface ModelDefinition {
  id:                string;
  model_id:          string;   // LiteLLM format, e.g. "anthropic/claude-3-haiku"
  provider:          string;
  context_window:    number;
  cost_per_1k_tokens: number;
  latency_tier:      LatencyTier;
  capabilities:      ModelCapability[];
  is_active:         boolean;
  created_at:        string;
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api" });
api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) cfg.headers.Authorization = `Bearer ${JSON.parse(raw).token}`;
  return cfg;
});

export const MODEL_KEYS = {
  all:    ["models"]                 as const,
  detail: (id: string) => ["models", id] as const,
};

export function useModels() {
  return useQuery({
    queryKey: MODEL_KEYS.all,
    queryFn:  () =>
      api.get<ModelDefinition[]>("/v1/models").then((r) => r.data),
  });
}

export function useToggleModelStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ modelId, isActive }: { modelId: string; isActive: boolean }) =>
      api.patch(`/v1/models/${modelId}/status`, { is_active: isActive }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: MODEL_KEYS.all }),
  });
}
```

---

### `ModelListPage`

```tsx
// frontend/admin-portal/src/pages/models/ModelListPage.tsx
import { Link }        from "react-router-dom";
import { useModels }   from "../../services/modelService";
import { ModelRow }    from "../../components/models/ModelRow";

export default function ModelListPage() {
  const { data: models, isLoading, isError } = useModels();

  return (
    <main aria-labelledby="models-heading">
      <div className="flex items-center justify-between mb-6">
        <h1 id="models-heading" className="text-2xl font-semibold">AI Models</h1>
        <div className="flex gap-2">
          <Link to="/models/add"     className="btn-primary"   aria-label="Register new AI model">Add Model</Link>
          <Link to="/models/weights" className="btn-secondary" aria-label="Configure routing weights">Routing Weights</Link>
        </div>
      </div>

      {isLoading && <p role="status" aria-live="polite">Loading models…</p>}
      {isError   && <p role="alert">Failed to load models. Please retry.</p>}

      {models && (
        <table className="w-full border-collapse text-sm" aria-label="Registered AI models">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase bg-gray-50">
              <th scope="col" className="px-4 py-2">Model ID</th>
              <th scope="col" className="px-4 py-2">Provider</th>
              <th scope="col" className="px-4 py-2">Context</th>
              <th scope="col" className="px-4 py-2">Cost / 1k</th>
              <th scope="col" className="px-4 py-2">Latency</th>
              <th scope="col" className="px-4 py-2">Capabilities</th>
              <th scope="col" className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => <ModelRow key={m.id} model={m} />)}
          </tbody>
        </table>
      )}
    </main>
  );
}
```

---

### `LatencyBadge`, `CapabilityTagList`, `ModelRow`

```tsx
// frontend/admin-portal/src/components/models/LatencyBadge.tsx
import type { LatencyTier } from "../../services/modelService";

const TIER: Record<LatencyTier, { label: string; className: string }> = {
  fast:   { label: "Fast",   className: "badge-green"  },
  medium: { label: "Medium", className: "badge-yellow" },
  slow:   { label: "Slow",   className: "badge-red"    },
};

export function LatencyBadge({ tier }: { tier: LatencyTier }) {
  const { label, className } = TIER[tier];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}
          aria-label={`Latency: ${label}`}>
      {label}
    </span>
  );
}
```

```tsx
// frontend/admin-portal/src/components/models/CapabilityTagList.tsx
import type { ModelCapability } from "../../services/modelService";

export function CapabilityTagList({ capabilities }: { capabilities: ModelCapability[] }) {
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Capabilities">
      {capabilities.map((c) => (
        <li key={c}
            className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-xs font-mono">
          {c}
        </li>
      ))}
    </ul>
  );
}
```

```tsx
// frontend/admin-portal/src/components/models/ModelRow.tsx
import * as Switch                from "@radix-ui/react-switch";
import { LatencyBadge }           from "./LatencyBadge";
import { CapabilityTagList }      from "./CapabilityTagList";
import { useToggleModelStatus }   from "../../services/modelService";
import type { ModelDefinition }   from "../../services/modelService";

interface Props { model: ModelDefinition; }

export function ModelRow({ model }: Props) {
  const { mutate: toggle, isPending } = useToggleModelStatus();

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="px-4 py-2 font-mono text-xs">{model.model_id}</td>
      <td className="px-4 py-2">{model.provider}</td>
      <td className="px-4 py-2">{model.context_window.toLocaleString()}</td>
      <td className="px-4 py-2">${model.cost_per_1k_tokens.toFixed(4)}</td>
      <td className="px-4 py-2"><LatencyBadge tier={model.latency_tier} /></td>
      <td className="px-4 py-2"><CapabilityTagList capabilities={model.capabilities} /></td>
      <td className="px-4 py-2">
        <Switch.Root
          checked={model.is_active}
          onCheckedChange={(checked) => toggle({ modelId: model.model_id, isActive: checked })}
          disabled={isPending}
          aria-label={model.is_active ? `Deactivate ${model.model_id}` : `Activate ${model.model_id}`}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
            ${model.is_active ? "bg-blue-600" : "bg-gray-300"}
            ${isPending ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
        >
          <Switch.Thumb className="block h-4 w-4 rounded-full bg-white shadow
            transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5" />
        </Switch.Root>
      </td>
    </tr>
  );
}
```

---

### Route registration

```tsx
// frontend/admin-portal/src/routes/index.tsx  (extend ADMIN_ROUTES)
const ModelListPage    = lazy(() => import("../pages/models/ModelListPage"));
const AddModelPage     = lazy(() => import("../pages/models/AddModelPage"));         // Task 2
const RoutingWeights   = lazy(() => import("../pages/models/RoutingWeightsPage"));  // Task 3

// Add inside the children array:
{ path: "models",          element: <ModelListPage /> },
{ path: "models/add",      element: <AddModelPage /> },
{ path: "models/weights",  element: <RoutingWeights /> },
```

## Acceptance Criteria

- [ ] Model table renders: `model_id`, `provider`, `context_window` (locale-formatted), `cost_per_1k_tokens` (4 d.p.), `latency_tier` badge, `capabilities` tag list, active toggle (AC-1)
- [ ] `PATCH /v1/models/{id}/status` sets `is_active=False`; the model is excluded from `GET /v1/models` (active-only) within the next Redis cache TTL — satisfying the 30 s SLA (AC-5)
- [ ] Toggle switch `aria-label` reflects the action — "Activate" when inactive, "Deactivate" when active (WCAG 2.1 AA)
- [ ] `context_window` and `cost_per_1k_tokens` are formatted numerically, not as raw integers (AC-1)
- [ ] All table headers have `scope="col"`; capability list has `aria-label="Capabilities"` (WCAG 2.1 AA)

## Dependencies

- TASK-US039-01 — `ADMIN_ROUTES` shell, `api` axios instance
- US-018 TASK-US018-04 — `GET /v1/models` and `POST /v1/models` routes; `model_router.py` extended
- US-018 TASK-US018-03 — `ModelRegistryService.set_active()` must be implemented

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] `PATCH /v1/models/{id}/status` + Redis invalidation: `mypy --strict` passes
- [ ] React Testing Library: list renders, deactivate toggle fires PATCH
