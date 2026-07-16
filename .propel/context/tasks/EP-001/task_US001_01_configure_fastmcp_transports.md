# TASK-US001-01 — Configure FastMCP Server with SSE and WebSocket Transport

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US001-01 |
| User Story | US-001 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | In Progress |

## Description

Bootstrap the FastMCP application and configure it to accept both SSE and WebSocket transport connections on the configured endpoint path. The server must be stateless and horizontally scalable.

## Implementation Details

**Technology:** Python 3.11+, FastMCP, FastAPI, `uvicorn`

**File locations:**
- `src/gateway/main.py` — FastAPI application factory
- `src/gateway/mcp_server.py` — FastMCP server instance and transport registration
- `src/gateway/config.py` — Pydantic `Settings` model for env-based config

**Key implementation steps:**

1. Create `FastMCP` instance with server metadata:
   ```python
   mcp = FastMCP(
       name="ContextIQ MCP Gateway",
       version=settings.version,
   )
   ```
2. Mount both transports on the FastAPI app:
   - SSE transport at `GET /mcp/sse` (event-stream)
   - WebSocket transport at `WS /mcp/ws`
3. Read endpoint path from `CONTEXTIQ_MCP_PATH` environment variable (default: `/mcp`)
4. Configure `uvicorn` with `--workers 1` per pod (async, not multi-process) behind a K8s HPA
5. Implement `GET /healthz` endpoint returning `{"status": "ok", "transport": ["sse", "websocket"]}`

**Environment variables required:**
```
CONTEXTIQ_MCP_PATH=/mcp
CONTEXTIQ_SERVER_VERSION=0.1.0
CONTEXTIQ_LOG_LEVEL=INFO
```

## Acceptance Criteria

- [x] FastMCP server starts without error when `uvicorn src.gateway.main:app` is run
- [x] `GET /healthz` returns HTTP 200 with `{"status": "ok"}`
- [x] SSE client can connect to `GET /mcp/sse` and receives a streaming response
- [x] WebSocket client can connect to `WS /mcp/ws` and completes handshake
- [x] Endpoint path is read from `CONTEXTIQ_MCP_PATH` env var at startup
- [x] Unit tests cover: server initialization, health endpoint, transport mount

## Dependencies

- EP-TECH-001 K8s pod is running (US-045) for integration testing
- FastMCP library pinned to `>=2.0.0` in `pyproject.toml`

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/gateway/`
- [ ] `GET /healthz` passes Kubernetes readiness probe check in staging
- [ ] No `ruff` lint errors; `mypy --strict` passes
