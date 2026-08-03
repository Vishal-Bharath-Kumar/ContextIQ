# TASK-US002-02 — Build PostgreSQL-Backed Tool Registry with Lifecycle API

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US002-02 |
| User Story | US-002 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 5 |
| Status | Draft |

## Description

Implement the `tool_registry` database table and the service layer + Admin REST API for registering, updating, enabling, and disabling MCP tools. This is the source of truth that feeds the `tools/list` handler and the Redis cache.

## Implementation Details

**Technology:** Python 3.11+, FastAPI, SQLAlchemy 2.x async, Alembic, PostgreSQL 15

**File locations:**
- `src/registry/models/tool.py` — SQLAlchemy `Tool` ORM model
- `src/registry/repositories/tool_repository.py` — async DB queries
- `src/registry/services/tool_registry_service.py` — business logic
- `src/registry/routers/tool_router.py` — `POST/GET/PATCH /v1/tools` endpoints
- `alembic/versions/0002_create_tool_registry.py` — migration
- `tests/registry/test_tool_registry_service.py`

**Database schema (`tool_registry` table):**

```sql
CREATE TABLE tool_registry (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(128) NOT NULL UNIQUE,
    description TEXT NOT NULL,
    input_schema JSONB NOT NULL DEFAULT '{}',
    status      VARCHAR(16) NOT NULL DEFAULT 'active'  -- active | inactive
        CHECK (status IN ('active', 'inactive')),
    version     VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_registry_status ON tool_registry (status);
```

**Admin API endpoints:**

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/tools` | Register a new tool definition |
| `GET` | `/v1/tools` | List all tools (supports `?status=active`) |
| `GET` | `/v1/tools/{name}` | Fetch single tool by name |
| `PATCH` | `/v1/tools/{name}` | Update description, schema, or status |
| `DELETE` | `/v1/tools/{name}` | Soft-delete (sets `status = 'inactive'`) |

**Registration payload example:**
```json
{
  "name": "get_context",
  "description": "Retrieve enterprise context for the given prompt",
  "inputSchema": {
    "type": "object",
    "properties": {
      "prompt": {"type": "string"},
      "max_tokens": {"type": "integer", "default": 4096}
    },
    "required": ["prompt"]
  }
}
```

**Post-write cache invalidation:** After any mutating operation, emit a Redis pub/sub event on channel `contextiq:tool_registry:changed` to trigger cache invalidation (consumed by TASK-US002-03).

## Acceptance Criteria

- [ ] `POST /v1/tools` creates a tool and returns HTTP 201 with the created `ToolDefinition`
- [ ] `POST /v1/tools` with a duplicate `name` returns HTTP 409
- [ ] `GET /v1/tools?status=active` returns only `status = 'active'` tools
- [ ] `PATCH /v1/tools/{name}` with `{"status": "inactive"}` disables the tool
- [ ] Alembic migration `0002_create_tool_registry.py` applies cleanly on a fresh PostgreSQL instance
- [ ] Redis pub/sub event is published within 100 ms of any mutating API call
- [ ] Unit tests cover: create, duplicate conflict, list-filtered, patch status, soft-delete

## Dependencies

- TASK-US001-01 (shared FastAPI app instance)
- EP-DATA-001 PostgreSQL store (US-050)
- EP-DATA-001 Redis store (US-051)

## Definition of Done

- [ ] Alembic migration merged and applied in staging database
- [ ] Admin API endpoints documented in OpenAPI (`/docs`)
- [ ] Unit test coverage ≥ 85% for `services/tool_registry_service.py`
- [ ] RBAC guard: `POST/PATCH/DELETE` require `ADMIN` or `PLATFORM_ENGINEER` role (enforced via dependency)
