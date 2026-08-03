# TASK-US044-04 — Audit Log Query API and Admin Portal Viewer

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US044-04 |
| User Story | US-044 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Done |

## Description

Implement the `GET /v1/audit-log` query API supporting filter parameters — `user`, `action`, `resource_type`, `resource_id`, and `date_from`/`date_to` — with cursor-based pagination (AC-4). Add the `AuditLogPage` React component in the Admin Portal accessible only to users with the `AUDITOR` or `ADMIN` role (AC-5). The page displays a filterable, paginated table of audit entries with all AC-1 fields visible: action, resource, actor, IP address, and timestamp.

## Implementation Details

**Technology (backend):** Python 3.11+, FastAPI, SQLAlchemy 2.x async, Pydantic v2
**Technology (frontend):** React 18, TypeScript, TanStack Query v5, React Hook Form v7, Zod v3, date-fns, Radix UI

**File locations:**
- `src/audit/admin_audit_log/query_repository.py` — `AuditLogQueryRepository` (filtered list + cursor pagination)
- `src/api/admin/routes/audit_log.py` — `GET /v1/audit-log` route
- `frontend/admin-portal/src/pages/AuditLogPage.tsx`
- `frontend/admin-portal/src/components/audit/AuditLogTable.tsx`
- `frontend/admin-portal/src/components/audit/AuditLogFilterBar.tsx`
- `frontend/admin-portal/src/services/auditLogService.ts`

---

### Query repository

```python
# src/audit/admin_audit_log/query_repository.py
from __future__ import annotations
import uuid
from datetime   import datetime
from typing     import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.admin_audit_log.models import AdminAuditLog

_PAGE_SIZE = 50


class AuditLogQueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        *,
        actor_user_id: str | None        = None,
        action:        str | None        = None,
        resource_type: str | None        = None,
        resource_id:   str | None        = None,
        date_from:     datetime | None   = None,
        date_to:       datetime | None   = None,
        cursor_id:     uuid.UUID | None  = None,   # ID of last row seen (for keyset pagination)
        limit:         int               = _PAGE_SIZE,
    ) -> list[AdminAuditLog]:
        """
        AC-4: Filtered + paginated query.

        Cursor pagination: next page is identified by the UUID of the last row
        returned (ordered by timestamp ASC, id ASC). Avoids OFFSET scans on
        large tables.
        """
        conditions = []

        if actor_user_id:
            conditions.append(AdminAuditLog.actor_user_id == actor_user_id)
        if action:
            conditions.append(AdminAuditLog.action == action)
        if resource_type:
            conditions.append(AdminAuditLog.resource_type == resource_type)
        if resource_id:
            conditions.append(AdminAuditLog.resource_id == resource_id)
        if date_from:
            conditions.append(AdminAuditLog.timestamp >= date_from)
        if date_to:
            conditions.append(AdminAuditLog.timestamp <= date_to)

        if cursor_id is not None:
            # Keyset pagination: fetch rows with id > cursor_id (ordered by id ASC)
            conditions.append(AdminAuditLog.id > cursor_id)

        stmt = (
            select(AdminAuditLog)
            .where(and_(*conditions) if conditions else True)
            .order_by(AdminAuditLog.timestamp.asc(), AdminAuditLog.id.asc())
            .limit(min(limit, _PAGE_SIZE))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
```

---

### `GET /v1/audit-log` route

```python
# src/api/admin/routes/audit_log.py
from __future__ import annotations
import uuid
from datetime import datetime
from typing   import Annotated

from fastapi              import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session                               import get_session
from src.audit.admin_audit_log.query_repository   import AuditLogQueryRepository
from src.audit.admin_audit_log.schemas            import AuditLogEntry
from src.auth.rbac                                import require_auditor
from pydantic                                     import BaseModel

router = APIRouter(prefix="/v1/audit-log", tags=["audit-log"])


class AuditLogListResponse(BaseModel):
    items:      list[AuditLogEntry]
    next_cursor: uuid.UUID | None   # None → no more pages


@router.get(
    "",
    response_model   = AuditLogListResponse,
    dependencies     = [Depends(require_auditor)],  # AUDITOR or ADMIN (US-042 matrix)
    summary          = "Query audit log",
    description      = "AC-4: Filter by user, action, resource, and date range.",
)
async def list_audit_log(
    session:       Annotated[AsyncSession, Depends(get_session)],
    actor_user_id: Annotated[str | None,      Query(alias="user")]          = None,
    action:        Annotated[str | None,      Query()]                      = None,
    resource_type: Annotated[str | None,      Query()]                      = None,
    resource_id:   Annotated[str | None,      Query()]                      = None,
    date_from:     Annotated[datetime | None, Query()]                      = None,
    date_to:       Annotated[datetime | None, Query()]                      = None,
    cursor:        Annotated[uuid.UUID | None, Query()]                     = None,
    limit:         Annotated[int,             Query(ge=1, le=100)]          = 50,
) -> AuditLogListResponse:
    repo = AuditLogQueryRepository(session)
    rows = await repo.list_filtered(
        actor_user_id = actor_user_id,
        action        = action,
        resource_type = resource_type,
        resource_id   = resource_id,
        date_from     = date_from,
        date_to       = date_to,
        cursor_id     = cursor,
        limit         = limit,
    )
    items = [
        AuditLogEntry(
            id            = row.id,
            action        = row.action,
            resource_type = row.resource_type,
            resource_id   = row.resource_id,
            actor_user_id = row.actor_user_id,
            ip_address    = row.ip_address,
            before_state  = row.before_state,
            after_state   = row.after_state,
            timestamp     = row.timestamp,
            row_hash      = row.row_hash,
        )
        for row in rows
    ]
    next_cursor = rows[-1].id if len(rows) == limit else None
    return AuditLogListResponse(items=items, next_cursor=next_cursor)
```

---

### Frontend: `auditLogService.ts`

```typescript
// frontend/admin-portal/src/services/auditLogService.ts
import { useInfiniteQuery } from "@tanstack/react-query";
import axios from "axios";

export interface AuditLogEntry {
  id:            string;
  action:        string;
  resource_type: string;
  resource_id:   string;
  actor_user_id: string;
  ip_address:    string;
  before_state:  Record<string, unknown> | null;
  after_state:   Record<string, unknown> | null;
  timestamp:     string;
  row_hash:      string;
}

export interface AuditLogFilters {
  user?:          string;
  action?:        string;
  resource_type?: string;
  resource_id?:   string;
  date_from?:     string;   // ISO 8601
  date_to?:       string;
}

export const AUDIT_KEYS = {
  list: (filters: AuditLogFilters) => ["audit-log", filters] as const,
};

export function useAuditLog(filters: AuditLogFilters) {
  return useInfiniteQuery({
    queryKey:         AUDIT_KEYS.list(filters),
    queryFn:          async ({ pageParam }) => {
      const params = new URLSearchParams();
      if (filters.user)          params.set("user",          filters.user);
      if (filters.action)        params.set("action",        filters.action);
      if (filters.resource_type) params.set("resource_type", filters.resource_type);
      if (filters.resource_id)   params.set("resource_id",   filters.resource_id);
      if (filters.date_from)     params.set("date_from",     filters.date_from);
      if (filters.date_to)       params.set("date_to",       filters.date_to);
      if (pageParam)             params.set("cursor",        pageParam as string);
      const { data } = await axios.get<{
        items: AuditLogEntry[];
        next_cursor: string | null;
      }>(`/v1/audit-log?${params.toString()}`);
      return data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime:        60_000,   // 1 min — audit log changes slowly
  });
}
```

---

### `AuditLogFilterBar` component

```tsx
// frontend/admin-portal/src/components/audit/AuditLogFilterBar.tsx
import { useForm }              from "react-hook-form";
import { zodResolver }          from "@hookform/resolvers/zod";
import { z }                    from "zod";
import type { AuditLogFilters } from "../../services/auditLogService";

const filterSchema = z.object({
  user:          z.string().optional(),
  action:        z.string().optional(),
  resource_type: z.string().optional(),
  resource_id:   z.string().optional(),
  date_from:     z.string().optional(),
  date_to:       z.string().optional(),
});

type FilterFormValues = z.infer<typeof filterSchema>;

interface Props {
  onFilter: (filters: AuditLogFilters) => void;
}

export function AuditLogFilterBar({ onFilter }: Props) {
  const { register, handleSubmit, reset } = useForm<FilterFormValues>({
    resolver: zodResolver(filterSchema),
  });

  return (
    <form
      onSubmit={handleSubmit(onFilter)}
      aria-label="Audit log filters"
      className="flex flex-wrap gap-2 p-4 bg-surface-subtle rounded-lg"
    >
      <input
        {...register("user")}
        placeholder="User ID"
        aria-label="Filter by user ID"
        className="input"
      />
      <input
        {...register("action")}
        placeholder="Action (e.g. policy.created)"
        aria-label="Filter by action"
        className="input"
      />
      <input
        {...register("resource_type")}
        placeholder="Resource type"
        aria-label="Filter by resource type"
        className="input"
      />
      <input
        {...register("resource_id")}
        placeholder="Resource ID"
        aria-label="Filter by resource ID"
        className="input"
      />
      <input
        {...register("date_from")}
        type="datetime-local"
        aria-label="From date"
        className="input"
      />
      <input
        {...register("date_to")}
        type="datetime-local"
        aria-label="To date"
        className="input"
      />
      <button type="submit" className="btn-primary">Apply</button>
      <button type="button" onClick={() => reset()} className="btn-secondary">Clear</button>
    </form>
  );
}
```

---

### `AuditLogPage` with role guard

```tsx
// frontend/admin-portal/src/pages/AuditLogPage.tsx
import { useState }                      from "react";
import { RequireAuditor }                from "../guards/RequireRoles";
import { AuditLogFilterBar }             from "../components/audit/AuditLogFilterBar";
import { AuditLogTable }                 from "../components/audit/AuditLogTable";
import { useAuditLog, AuditLogFilters }  from "../services/auditLogService";

export function AuditLogPage() {
  const [filters, setFilters] = useState<AuditLogFilters>({});
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useAuditLog(filters);

  const allEntries = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    // AC-5: AUDITOR or ADMIN role required
    <RequireAuditor>
      <main aria-labelledby="audit-log-heading" className="page-layout">
        <h1 id="audit-log-heading" className="page-title">Audit Log</h1>

        <AuditLogFilterBar onFilter={setFilters} />

        {isLoading ? (
          <p role="status" aria-live="polite">Loading audit log…</p>
        ) : (
          <AuditLogTable entries={allEntries} />
        )}

        {hasNextPage && (
          <button
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
            className="btn-secondary mt-4"
            aria-label="Load next page of audit log entries"
          >
            {isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        )}
      </main>
    </RequireAuditor>
  );
}
```

---

### Route registration

```typescript
// frontend/admin-portal/src/App.tsx  (extend ADMIN_ROUTES — add audit log route)
{
  path:      "audit-log",
  element:   lazy(() => import("./pages/AuditLogPage")),
  // RequireAuditor guard is applied inside AuditLogPage
}
```

## Acceptance Criteria

- [x] `GET /v1/audit-log` filters by `user`, `action`, `resource_type`, `resource_id`, `date_from`, `date_to` (AC-4)
- [x] Cursor-based pagination: `next_cursor` is the last row's opaque cursor; `null` when no further pages (AC-4)
- [x] Endpoint returns HTTP 403 for callers without `AUDITOR` or `ADMIN` role (AC-5)
- [x] `AuditLogPage` renders only when user has `AUDITOR` or `ADMIN` role via `RequireAuditor` guard (AC-5, US-042 TASK-US042-04)
- [x] All AC-1 fields are visible in `AuditLogTable`: action, resource, actor, IP address, timestamp (AC-1, AC-5)
- [x] Filter form uses `aria-label` on every input; pagination button has `aria-label` (WCAG 2.1 AA)
- [x] `useAuditLog` uses TanStack Query `useInfiniteQuery` with `staleTime: 60_000`

## Dependencies

- TASK-US044-01 — `AdminAuditLog` ORM, `AuditLogEntry` schema
- TASK-US042-02 — `require_auditor` named dependency; `RequireAuditor` guard
- TASK-US044-02 — rows must be written before they can be queried
- EP-013 US-039-01 — `ADMIN_ROUTES` lazy routing pattern

## Definition of Done

- [x] `pytest tests/audit/test_audit_log_query_route.py` passes (see TASK-US044-05)
- [x] `pnpm test` passes `AuditLogPage.test.tsx` and `AuditLogFilterBar.test.tsx`
- [x] `mypy --strict src/audit/admin_audit_log/query_repository.py src/api/admin/routes/audit_log.py` passes
