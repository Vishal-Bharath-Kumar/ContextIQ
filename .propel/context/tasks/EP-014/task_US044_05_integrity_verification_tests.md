# TASK-US044-05 — Integrity Verification Endpoint and Full Integration Test Suite

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US044-05 |
| User Story | US-044 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Backend / Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `GET /v1/audit-log/verify` endpoint that re-computes the SHA-256 chain hash over every row in `admin_audit_log` (ordered by `timestamp` ASC, `id` ASC) and reports whether the stored hashes match the recomputed values (AC-6). Write the integration test suite covering all 6 US-044 acceptance criteria: pytest tests for the immutability trigger, write-on-mutation, query filtering, MinIO archival, role-gating, and chain integrity. React Testing Library tests cover the `AuditLogPage` and `AuditLogFilterBar` components.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `httpx.AsyncClient` + `ASGITransport`, `moto[s3]>=5.0`, React Testing Library, Vitest, MSW

**File locations:**
- `src/api/admin/routes/audit_log.py` — extend with `GET /v1/audit-log/verify`
- `tests/audit/test_audit_immutability.py` — AC-2: PostgreSQL trigger tests
- `tests/audit/test_audit_write_on_mutation.py` — AC-1: row written for each mutating route
- `tests/audit/test_audit_query_filters.py` — AC-4: filter + pagination
- `tests/audit/test_archive_service.py` — AC-3: MinIO archival via `moto[s3]`
- `tests/audit/test_audit_rbac.py` — AC-5: 403 for non-AUDITOR roles
- `tests/audit/test_hash_chain.py` — AC-6: hash chain integrity
- `frontend/admin-portal/src/__tests__/AuditLogPage.test.tsx`

---

### `GET /v1/audit-log/verify` endpoint

```python
# src/api/admin/routes/audit_log.py  (extend — add verify endpoint)
from src.audit.admin_audit_log.hash_chain import compute_row_hash, GENESIS_PREV_HASH, row_fields_for_hashing
from pydantic import BaseModel as _Base

class IntegrityVerificationResult(_Base):
    total_rows:     int
    first_mismatch: int | None    # 1-based row index; None if chain is intact
    is_intact:      bool


@router.get(
    "/verify",
    response_model   = IntegrityVerificationResult,
    dependencies     = [Depends(require_auditor)],
    summary          = "Verify audit log chain integrity",
    description      = "AC-6: Re-computes SHA-256 chain hashes and reports first mismatch.",
)
async def verify_audit_log_integrity(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntegrityVerificationResult:
    """
    Fetches ALL rows ordered by (timestamp ASC, id ASC) and re-derives the
    hash chain from GENESIS_PREV_HASH. Returns the first row index (1-based)
    where the recomputed hash diverges from the stored hash, or None if intact.

    Performance note: this scans the full table. For very large audit logs
    a date-range parameter can be added in a future iteration.
    """
    result = await session.execute(
        select(AdminAuditLog)
        .order_by(AdminAuditLog.timestamp.asc(), AdminAuditLog.id.asc())
    )
    rows = result.scalars().all()

    prev_hash     = GENESIS_PREV_HASH
    first_mismatch: int | None = None

    for idx, row in enumerate(rows, start=1):
        fields   = row_fields_for_hashing(
            action        = row.action,
            resource_type = row.resource_type,
            resource_id   = row.resource_id,
            actor_user_id = row.actor_user_id,
            ip_address    = row.ip_address,
            before_state  = row.before_state,
            after_state   = row.after_state,
            timestamp     = row.timestamp,
        )
        expected = compute_row_hash(prev_hash, fields)
        if row.row_hash != expected:
            first_mismatch = idx
            break
        prev_hash = row.row_hash

    return IntegrityVerificationResult(
        total_rows     = len(rows),
        first_mismatch = first_mismatch,
        is_intact      = first_mismatch is None,
    )
```

---

### AC-2: Immutability trigger tests

```python
# tests/audit/test_audit_immutability.py
import pytest
from sqlalchemy         import text
from sqlalchemy.exc     import DBAPIError


@pytest.mark.asyncio
async def test_update_admin_audit_log_raises(db_session, seed_audit_row):
    """AC-2: UPDATE on admin_audit_log raises PL/pgSQL exception."""
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.execute(
            text("UPDATE admin_audit_log SET action='tampered' WHERE id = :id"),
            {"id": str(seed_audit_row.id)},
        )


@pytest.mark.asyncio
async def test_delete_admin_audit_log_raises(db_session, seed_audit_row):
    """AC-2: DELETE on admin_audit_log raises PL/pgSQL exception."""
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.execute(
            text("DELETE FROM admin_audit_log WHERE id = :id"),
            {"id": str(seed_audit_row.id)},
        )
```

---

### AC-1: Row written for each mutating route

```python
# tests/audit/test_audit_write_on_mutation.py
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from src.main                              import app
from src.audit.admin_audit_log.models      import AdminAuditLog
from src.auth.testing                      import make_test_claims
from src.auth.roles                        import PlatformRole
from src.auth.dependencies                 import decode_jwt_claims


_PLATFORM_ENGINEER_CLAIMS = make_test_claims(PlatformRole.PLATFORM_ENGINEER)

@pytest.fixture(autouse=True)
def inject_claims():
    app.dependency_overrides[decode_jwt_claims] = lambda: _PLATFORM_ENGINEER_CLAIMS
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_policy_writes_audit_row(db_session, mock_policy_create):
    """AC-1: POST /v1/policies creates exactly one admin_audit_log row."""
    before = await db_session.scalar(select(func.count()).select_from(AdminAuditLog))
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/v1/policies",
            json    = {"name": "test-policy", "rego": "package test\ndefault allow = false"},
            headers = {"Authorization": "Bearer mock"},
        )
    assert response.status_code == 201
    after = await db_session.scalar(select(func.count()).select_from(AdminAuditLog))
    assert after == before + 1

    # Verify fields
    row = await db_session.scalar(
        select(AdminAuditLog).order_by(AdminAuditLog.timestamp.desc()).limit(1)
    )
    assert row is not None
    assert row.action        == "policy.created"
    assert row.resource_type == "policy"
    assert row.actor_user_id == _PLATFORM_ENGINEER_CLAIMS.sub
    assert row.ip_address    != ""
    assert row.before_state  is None          # create: no before state
    assert row.after_state   is not None      # create: after state populated


@pytest.mark.asyncio
async def test_update_model_status_writes_audit_row(db_session, seed_model):
    """AC-1: PATCH /v1/models/{id}/status creates one audit row with before/after state."""
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/models/{seed_model.id}/status",
            json    = {"active": False},
            headers = {"Authorization": "Bearer mock"},
        )
    assert response.status_code == 200
    row = await db_session.scalar(
        select(AdminAuditLog)
        .where(AdminAuditLog.resource_id == str(seed_model.id))
        .order_by(AdminAuditLog.timestamp.desc())
        .limit(1)
    )
    assert row is not None
    assert row.action       == "model.status_changed"
    assert row.before_state is not None
    assert row.after_state  is not None
```

---

### AC-4: Query filter tests

```python
# tests/audit/test_audit_query_filters.py
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app


@pytest.mark.asyncio
async def test_filter_by_action(db_session, seed_mixed_audit_rows, auditor_auth_header):
    """AC-4: ?action=policy.created returns only policy.created rows."""
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/v1/audit-log?action=policy.created",
            headers=auditor_auth_header,
        )
    assert response.status_code == 200
    data = response.json()
    assert all(item["action"] == "policy.created" for item in data["items"])


@pytest.mark.asyncio
async def test_filter_by_user(db_session, seed_mixed_audit_rows, auditor_auth_header):
    """AC-4: ?user=user-001 returns only rows for that actor."""
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(
            "/v1/audit-log?user=user-001",
            headers=auditor_auth_header,
        )
    assert response.status_code == 200
    data = response.json()
    assert all(item["actor_user_id"] == "user-001" for item in data["items"])


@pytest.mark.asyncio
async def test_pagination_cursor(db_session, seed_60_audit_rows, auditor_auth_header):
    """AC-4: Second page returned via cursor is non-overlapping with first page."""
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        first  = (await client.get("/v1/audit-log?limit=50", headers=auditor_auth_header)).json()
        cursor = first["next_cursor"]
        assert cursor is not None
        second = (await client.get(f"/v1/audit-log?limit=50&cursor={cursor}", headers=auditor_auth_header)).json()

    first_ids  = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)
```

---

### AC-3: MinIO archival tests

```python
# tests/audit/test_archive_service.py
import gzip, json, pytest
from datetime   import date
from moto       import mock_aws

from src.audit.admin_audit_log.archive_service  import AuditArchiveService
from src.audit.admin_audit_log.archive_settings import ArchiveSettings


@pytest.fixture
def archive_settings():
    return ArchiveSettings(
        minio_endpoint   = "http://localhost:5555",   # ignored by moto
        minio_bucket     = "contextiq-audit-archive",
        minio_access_key = "test",
        minio_secret_key = "test",
        minio_region     = "us-east-1",
    )


@mock_aws
@pytest.mark.asyncio
async def test_archive_uploads_correct_key(db_session, seed_audit_rows_yesterday, archive_settings):
    """AC-3: archive_day uploads to audit-log/{YYYY}/{MM}/{DD}.ndjson.gz."""
    import aiobotocore.session as abc_session
    import boto3

    # Pre-create bucket in moto
    boto3.client("s3", region_name="us-east-1").create_bucket(
        Bucket=archive_settings.minio_bucket
    )

    service  = AuditArchiveService(archive_settings)
    day      = date(2026, 7, 9)   # yesterday relative to test date
    count    = await service.archive_day(db_session, day=day)

    assert count > 0

    s3       = boto3.client("s3", region_name="us-east-1")
    obj      = s3.get_object(
        Bucket = archive_settings.minio_bucket,
        Key    = f"audit-log/2026/07/09.ndjson.gz",
    )
    body     = obj["Body"].read()
    lines    = gzip.decompress(body).decode("utf-8").strip().splitlines()
    rows     = [json.loads(line) for line in lines]

    assert len(rows) == count
    assert all("row_hash" in row for row in rows)   # AC-6 hash included in archive


@mock_aws
@pytest.mark.asyncio
async def test_archive_no_rows_skips_upload(db_session, archive_settings):
    """AC-3: If no rows for the target day, no object is uploaded."""
    import boto3
    boto3.client("s3", region_name="us-east-1").create_bucket(
        Bucket=archive_settings.minio_bucket
    )
    service = AuditArchiveService(archive_settings)
    count   = await service.archive_day(db_session, day=date(2020, 1, 1))
    assert count == 0
```

---

### AC-5 + AC-6 combined: RBAC and integrity tests

```python
# tests/audit/test_audit_rbac.py
import pytest
from httpx import AsyncClient, ASGITransport
from src.main        import app
from src.auth.testing import make_test_claims
from src.auth.roles   import PlatformRole
from src.auth.dependencies import decode_jwt_claims


@pytest.mark.parametrize("role", [
    PlatformRole.DEVELOPER,
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.DEVOPS_SRE,
    PlatformRole.MANAGER,
    PlatformRole.SECURITY_OFFICER,
])
@pytest.mark.asyncio
async def test_non_auditor_roles_denied(role):
    """AC-5: Only AUDITOR and ADMIN may access GET /v1/audit-log."""
    app.dependency_overrides[decode_jwt_claims] = lambda: make_test_claims(role)
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/v1/audit-log")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


# tests/audit/test_hash_chain.py
import pytest
from src.audit.admin_audit_log.hash_chain import (
    compute_row_hash, GENESIS_PREV_HASH, row_fields_for_hashing,
)
from datetime import datetime, timezone


class TestHashChain:
    """AC-6: SHA-256 chain integrity tests."""

    def _fields(self, action: str = "policy.created") -> dict:
        return row_fields_for_hashing(
            action        = action,
            resource_type = "policy",
            resource_id   = "pol-001",
            actor_user_id = "user-001",
            ip_address    = "10.0.0.1",
            before_state  = None,
            after_state   = {"name": "test"},
            timestamp     = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc),
        )

    def test_genesis_hash_is_deterministic(self):
        h1 = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        h2 = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        assert h1 == h2 and len(h1) == 64

    def test_different_prev_hash_produces_different_row_hash(self):
        h1 = compute_row_hash(GENESIS_PREV_HASH, self._fields())
        h2 = compute_row_hash("a" * 64,          self._fields())
        assert h1 != h2

    def test_tampered_field_produces_different_hash(self):
        base_fields    = self._fields()
        tampered_fields = self._fields(action="tampered.action")
        h_base    = compute_row_hash(GENESIS_PREV_HASH, base_fields)
        h_tampered = compute_row_hash(GENESIS_PREV_HASH, tampered_fields)
        assert h_base != h_tampered

    def test_chain_of_three_rows(self):
        """Verify a 3-row chain: each row's hash is the next row's prev_hash input."""
        h0 = GENESIS_PREV_HASH
        h1 = compute_row_hash(h0, self._fields("policy.created"))
        h2 = compute_row_hash(h1, self._fields("policy.activated"))
        h3 = compute_row_hash(h2, self._fields("policy.rolled_back"))
        # Re-deriving h1 from h0 must produce the same result
        assert compute_row_hash(h0, self._fields("policy.created")) == h1
        assert len({h1, h2, h3}) == 3    # all distinct
```

---

### Frontend: `AuditLogPage` component tests

```tsx
// frontend/admin-portal/src/__tests__/AuditLogPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent                   from "@testing-library/user-event";
import { MemoryRouter }            from "react-router-dom";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { AuditLogPage }            from "../pages/AuditLogPage";
import { AuthProvider }            from "../context/AuthContext";
import { http, HttpResponse }      from "msw";
import { setupServer }             from "msw/node";

const MOCK_ENTRIES = [
  {
    id: "aaa-111", action: "policy.created", resource_type: "policy",
    resource_id: "pol-1", actor_user_id: "user-1", ip_address: "10.0.0.1",
    before_state: null, after_state: { name: "p1" }, timestamp: "2026-07-09T12:00:00Z",
    row_hash: "abc123",
  },
];

const server = setupServer(
  http.get("/v1/audit-log", () =>
    HttpResponse.json({ items: MOCK_ENTRIES, next_cursor: null })
  )
);
beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function Wrapper({ children }: { children: React.ReactNode }) {
  const mockUser = { userId: "u1", email: "a@b.com", roles: ["auditor"], token: "t" };
  return (
    <MemoryRouter>
      <AuthProvider _mockUser={mockUser}>
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          {children}
        </QueryClientProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("AuditLogPage — AC-5", () => {
  it("renders audit table for AUDITOR role", async () => {
    render(<AuditLogPage />, { wrapper: Wrapper });
    await waitFor(() =>
      expect(screen.getByText("policy.created")).toBeInTheDocument()
    );
  });

  it("renders actor_user_id and ip_address in table", async () => {
    render(<AuditLogPage />, { wrapper: Wrapper });
    await waitFor(() => {
      expect(screen.getByText("user-1")).toBeInTheDocument();
      expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
    });
  });

  it("redirects DEVELOPER role to /403", async () => {
    const devUser = { userId: "u2", email: "b@b.com", roles: ["developer"], token: "t" };
    render(
      <MemoryRouter>
        <AuthProvider _mockUser={devUser}>
          <QueryClientProvider client={new QueryClient()}>
            <AuditLogPage />
          </QueryClientProvider>
        </AuthProvider>
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(screen.queryByText("Audit Log")).not.toBeInTheDocument()
    );
  });
});
```

## Acceptance Criteria

- [ ] `test_update_admin_audit_log_raises` and `test_delete_admin_audit_log_raises` pass — PostgreSQL trigger enforces immutability (AC-2)
- [ ] `test_create_policy_writes_audit_row` — POST creates exactly 1 row with correct fields (AC-1)
- [ ] `test_update_model_status_writes_audit_row` — PATCH populates both `before_state` and `after_state` (AC-1)
- [ ] `test_filter_by_action`, `test_filter_by_user`, `test_pagination_cursor` pass (AC-4)
- [ ] `test_archive_uploads_correct_key` — NDJSON.gz object created at correct MinIO path (AC-3)
- [ ] `test_archive_no_rows_skips_upload` — no upload when there are no rows (AC-3)
- [ ] `test_non_auditor_roles_denied` (5 parametrized roles) return HTTP 403 (AC-5)
- [ ] `TestHashChain` — all 4 chain hash tests pass (AC-6)
- [ ] `GET /v1/audit-log/verify` returns `is_intact: true` for an unmodified chain (AC-6)
- [ ] `AuditLogPage.test.tsx` — renders for AUDITOR, redirects for DEVELOPER (AC-5)

## Dependencies

- TASK-US044-01 — `AdminAuditLog`, `compute_row_hash`, `GENESIS_PREV_HASH`
- TASK-US044-02 — audit hooks on mutating routes (needed for write-on-mutation tests)
- TASK-US044-03 — `AuditArchiveService` under test
- TASK-US044-04 — `GET /v1/audit-log` route + `AuditLogPage` component under test

## Definition of Done

- [ ] `pytest tests/audit/ -v` — all tests pass (no live Keycloak, PostgreSQL trigger tests use async real DB or a mock that honours the trigger)
- [ ] `pnpm test` passes all `AuditLogPage.test.tsx` cases
- [ ] `mypy --strict src/api/admin/routes/audit_log.py` passes (includes verify endpoint)
- [ ] Test execution time < 30 seconds (moto[s3], fakeredis, and test DB used throughout)
