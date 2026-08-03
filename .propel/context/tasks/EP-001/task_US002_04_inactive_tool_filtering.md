# TASK-US002-04 — Filter Inactive and Disabled Tools from Registry Response

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US002-04 |
| User Story | US-002 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Ensure the `tools/list` handler never surfaces tools with `status = 'inactive'` or that belong to a disabled connector. Filtering must be enforced at the query layer (not application layer) to prevent accidentally leaking disabled tool metadata.

## Implementation Details

**Technology:** Python 3.11+, SQLAlchemy 2.x async

**File locations:**
- `src/registry/repositories/tool_repository.py` — `find_active()` query
- `src/registry/services/tool_registry_service.py` — filtering integration
- `tests/registry/test_tool_filtering.py` — parametrised filtering tests

**Key implementation steps:**

1. **Repository-level filter** — `find_active()` enforces `status = 'active'` at the SQL level:
   ```python
   async def find_active(self) -> list[Tool]:
       stmt = (
           select(Tool)
           .where(Tool.status == "active")
           .order_by(Tool.name.asc())
       )
       result = await self.session.execute(stmt)
       return result.scalars().all()
   ```
   No application-level filtering of the full list after fetching — the WHERE clause is the gate.

2. **Connector-disabled tools:** A tool registered by a connector is also inactive when its parent connector's `status = 'inactive'`. Extend the query with a JOIN:
   ```python
   stmt = (
       select(Tool)
       .join(ConnectorConfig, Tool.connector_id == ConnectorConfig.id, isouter=True)
       .where(
           Tool.status == "active",
           or_(
               Tool.connector_id.is_(None),          # platform-native tools
               ConnectorConfig.status == "active",   # connector-backed tools
           )
       )
       .order_by(Tool.name.asc())
   )
   ```

3. **Schema update** — Add `connector_id` (nullable FK) column to `tool_registry` table via a new Alembic migration:
   ```python
   # alembic/versions/0003_tool_connector_fk.py
   op.add_column("tool_registry",
       sa.Column("connector_id", sa.UUID(), sa.ForeignKey("connector_config.id"), nullable=True)
   )
   ```

4. When a connector is disabled via Admin API, a `connector.status.changed` event is published; the tool cache is invalidated to prevent stale active-tool lists.

## Acceptance Criteria

- [ ] `tools/list` never includes a tool with `status = 'inactive'` — verified with a DB fixture containing mixed statuses
- [ ] `tools/list` excludes tools whose parent connector has `status = 'inactive'`
- [ ] Platform-native tools (no `connector_id`) are unaffected by connector status changes
- [ ] Disabling a connector via `PATCH /v1/connectors/{id}` triggers tool cache invalidation (verified in integration test)
- [ ] `find_active()` executes a single SQL query (no N+1) — confirmed via SQLAlchemy query logging in tests
- [ ] Parametrised unit tests cover: all active, some inactive, all inactive, connector-disabled

## Dependencies

- TASK-US002-02 (tool registry schema and `ConnectorConfig` table from US-025)
- TASK-US002-03 (cache invalidation on connector status change)

## Definition of Done

- [ ] Alembic migration `0003_tool_connector_fk.py` applied in staging
- [ ] Unit tests cover all filtering scenarios with ≥ 90% branch coverage
- [ ] SQL query confirmed single-statement (no N+1) via `echo=True` in test session
- [ ] `PATCH /v1/connectors/{id}` with `{"status": "inactive"}` confirmed to exclude affected tools from next `tools/list` call
