# TASK-US042-03 — Apply RBAC Guards to All Protected API Endpoint Groups

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US042-03 |
| User Story | US-042 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Done |

## Description

Wire the RBAC dependency callables from TASK-US042-02 to every protected FastAPI router (AC-3). Each router group receives the correct `Permission`-based dependency at the `APIRouter` level so that individual route functions do not need to repeat it. This is a surgical extension — one `dependencies=[...]` addition per router; no business logic changes.

## Implementation Details

**Technology:** Python 3.11+, FastAPI `APIRouter(dependencies=[...])`

**File locations (extend only — do NOT rewrite):**
- `src/gateway/mcp_handler.py` — MCP tool-call router
- `src/knowledge_sources/routers/knowledge_source_router.py` — EP-008 connector routes
- `src/model_registry/routers/model_router.py` — EP-006 model registry routes
- `src/model_router/routers/routing_weight_router.py` — EP-006/US-041 routing weights
- `src/api/admin/routes/policies.py` — EP-010 governance policy routes
- `src/api/admin/routes/replay.py` — EP-011 execution trace replay routes
- `src/api/admin/routes/model_analytics.py` — EP-012/US-041 cost analytics route
- `src/observability/metrics/router.py` — EP-012 Prometheus `/metrics` endpoint

---

### Router-level dependency pattern

Each router receives a single `dependencies=[Depends(...)]` addition at declaration. FastAPI injects the dependency before every route in the router — no per-route changes needed.

```python
# Pattern (applies to all routers below):
from src.auth import require_<X>

router = APIRouter(
    prefix      = "...",
    tags        = ["..."],
    dependencies = [Depends(require_<X>)],   # ← RBAC guard applied here
)
```

---

### 1. MCP tool-call gateway — `CALL_CONTEXT_TOOLS`

```python
# src/gateway/mcp_handler.py  (extend — add dependencies to existing FastMCP/router setup)
from fastapi import Depends
from src.auth import require_context_tools

# If using FastAPI router wrapping FastMCP:
mcp_router = APIRouter(
    prefix       = "/tools",
    dependencies = [Depends(require_context_tools)],
)
# Alternatively, add the Depends to the FastMCP middleware check:
# class MCPAuthMiddleware — call require_context_tools logic before invoking tool handler
```

---

### 2. Knowledge source / connector routes — `MANAGE_CONNECTORS`

```python
# src/knowledge_sources/routers/knowledge_source_router.py  (extend)
from src.auth import require_manage_connectors

# Replace the existing require_admin_role dependency on the router:
router = APIRouter(
    prefix       = "/v1/knowledge-sources",
    tags         = ["Knowledge Sources"],
    dependencies = [Depends(require_manage_connectors)],   # was: require_admin_role
)
```

---

### 3. Model registry routes — `MANAGE_MODELS`

```python
# src/model_registry/routers/model_router.py  (extend)
from src.auth import require_manage_models

router = APIRouter(
    prefix       = "/v1/models",
    tags         = ["Model Registry"],
    dependencies = [Depends(require_manage_models)],
)
```

---

### 4. Routing weight routes — `MANAGE_MODELS`

```python
# src/model_router/routers/routing_weight_router.py  (extend)
from src.auth import require_manage_models

router = APIRouter(
    prefix       = "/v1/routing/weights",
    tags         = ["Routing Weights"],
    dependencies = [Depends(require_manage_models)],
)
```

---

### 5. Governance policy routes — `MANAGE_POLICIES`

```python
# src/api/admin/routes/policies.py  (extend)
from src.auth import require_manage_policies

# Replace the per-route AdminClaims = Annotated[dict, Depends(require_admin_role)] pattern:
router = APIRouter(
    prefix       = "/v1/policies",
    tags         = ["Admin — Policies"],
    dependencies = [Depends(require_manage_policies)],
)
# Keep AdminClaims for routes that also need the claims object (e.g. for actor_user_id):
AdminClaims = Annotated[JWTClaims, Depends(require_manage_policies)]
```

---

### 6. Execution trace replay routes — `READ_TRACES`

```python
# src/api/admin/routes/replay.py  (extend)
from src.auth import require_read_traces

router = APIRouter(
    prefix       = "/v1/traces",
    tags         = ["Replay Explorer"],
    dependencies = [Depends(require_read_traces)],
)
```

---

### 7. Cost analytics route — `READ_COST_ANALYTICS`

```python
# src/api/admin/routes/model_analytics.py  (extend)
from src.auth import require_cost_analytics

router = APIRouter(
    prefix       = "/v1/models",
    tags         = ["Model Analytics"],
    dependencies = [Depends(require_cost_analytics)],
)
```

---

### 8. Prometheus `/metrics` endpoint — `READ_METRICS`

```python
# src/observability/metrics/router.py  (extend)
from fastapi import APIRouter, Depends
from src.auth import require_read_metrics

metrics_router = APIRouter(dependencies=[Depends(require_read_metrics)])

@metrics_router.get("/metrics")
async def prometheus_metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

---

### Consolidated router dependency summary

| Router prefix | Permission | Allowed roles |
|---|---|---|
| `/tools` (MCP) | `CALL_CONTEXT_TOOLS` | `DEVELOPER`, `PLATFORM_ENGINEER`, `ADMIN` |
| `/v1/knowledge-sources` | `MANAGE_CONNECTORS` | `PLATFORM_ENGINEER`, `ADMIN` |
| `/v1/models` (registry) | `MANAGE_MODELS` | `PLATFORM_ENGINEER`, `ADMIN` |
| `/v1/routing/weights` | `MANAGE_MODELS` | `PLATFORM_ENGINEER`, `ADMIN` |
| `/v1/policies` | `MANAGE_POLICIES` | `SECURITY_OFFICER`, `ADMIN` |
| `/v1/traces` | `READ_TRACES` | `AUDITOR`, `DEVOPS_SRE`, `SECURITY_OFFICER`, `ADMIN` |
| `/v1/models/cost-analytics` | `READ_COST_ANALYTICS` | `MANAGER`, `PLATFORM_ENGINEER`, `ADMIN` |
| `/metrics` | `READ_METRICS` | `DEVOPS_SRE`, `PLATFORM_ENGINEER`, `ADMIN` |

---

### Unauthenticated path exceptions (must remain open)

The following paths bypass RBAC and are excluded from the JWT middleware in `JWTAuthMiddleware`:

```python
# src/gateway/middleware/jwt_auth.py  (document in existing SKIP_PATHS set)
SKIP_PATHS: frozenset[str] = frozenset({
    "/healthz",        # readiness/liveness — no auth
    "/docs",           # FastAPI OpenAPI UI — auth optional (dev only)
    "/openapi.json",   # OpenAPI schema
    "/redoc",
})
```

## Acceptance Criteria

- [x] A `DEVELOPER`-role JWT receives HTTP 200 from `POST /tools/...` and HTTP 403 from `POST /v1/knowledge-sources` (AC-3)
- [x] An `AUDITOR`-role JWT receives HTTP 200 from `GET /v1/traces` and HTTP 403 from `GET /v1/policies` (AC-3)
- [x] A `MANAGER`-role JWT receives HTTP 200 from `GET /v1/models/cost-analytics` and HTTP 403 from `PATCH /v1/models/{id}/status` (AC-3)
- [x] A `DEVOPS_SRE`-role JWT receives HTTP 200 from `GET /metrics` and HTTP 403 from `POST /v1/policies` (AC-3)
- [x] An `ADMIN`-role JWT receives HTTP 200 from every protected endpoint (AC-1)
- [x] `/healthz` returns 200 with no `Authorization` header (bypass path)
- [x] No individual route function imports `require_admin_role` — all RBAC is applied at router level

## Dependencies

- TASK-US042-01 — `Permission`, `PlatformRole`
- TASK-US042-02 — `require_context_tools`, `require_manage_connectors`, etc.
- All existing routers (US-025, US-033, US-034, US-035, US-036, US-041)

## Definition of Done

- [x] `grep -r "require_admin_role" src/` finds zero results (all replaced by RBAC system)
- [x] `mypy --strict` passes across all modified router files
- [x] Integration smoke test: one 200 and one 403 per endpoint group (covered fully in TASK-US042-05)
