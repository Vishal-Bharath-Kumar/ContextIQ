# TASK-US033-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US033-05 |
| User Story | US-033 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the integration and unit test suite covering all 6 US-033 acceptance criteria: `POST /v1/policies` stores Rego with required fields (AC-1), all versions retained in PostgreSQL (AC-2), `POST /{id}/activate` triggers OPA bundle push (AC-3), rollback restores prior version (AC-4), audit fields recorded (AC-5), invalid Rego returns HTTP 422 with parse errors (AC-6).

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `respx`, `AsyncMock`, `unittest.mock`, FastAPI `TestClient` / `httpx.AsyncClient`

**File locations:**
- `tests/governance/test_policy_repository.py` — `PolicyRepository` unit tests (AC-2, AC-4)
- `tests/governance/test_rego_validator.py` — `RegoValidator` unit tests (AC-6)
- `tests/governance/test_policy_service.py` — `PolicyService` unit tests (AC-3, AC-4, AC-5, AC-6)
- `tests/api/test_policy_routes.py` — HTTP-level integration tests against FastAPI (all ACs)

---

### Shared fixtures

```python
# tests/governance/conftest.py  (extend existing file)
import pytest
from unittest.mock import AsyncMock

VALID_REGO = """
package contextiq.authz

default allow = false

allow {
    input.user_roles[_] == "developer"
}
"""

INVALID_REGO = "package contextiq.authz\nallow { syntax error here }"

POLICY_NAME    = "contextiq_policies"
POLICY_VERSION = "1.0.0"
ADMIN_AUTHOR   = "user-sub-abc123"


@pytest.fixture
def mock_opa_valid():
    """OPA that accepts Rego (200 on PUT /v1/policies/*)."""
    import respx, httpx
    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.put("/v1/policies/contextiq_policies").mock(
            return_value=httpx.Response(200, json={"result": None})
        )
        mock.delete("/v1/policies/_rego_validation_contextiq_policies").mock(
            return_value=httpx.Response(200)
        )
        yield mock


@pytest.fixture
def mock_opa_invalid():
    """OPA that rejects Rego with 400 parse error."""
    import respx, httpx
    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.put("/v1/policies/_rego_validation_contextiq_policies").mock(
            return_value=httpx.Response(400, json={
                "code": "invalid_parameter",
                "message": "1 error occurred",
                "errors": [
                    {"message": "1 error occurred: rego_parse_error: unexpected token 'error'"}
                ],
            })
        )
        yield mock
```

---

### AC-1 — `POST /v1/policies` stores required fields

```python
# tests/api/test_policy_routes.py
async def test_create_policy_stores_required_fields(async_client, mock_opa_valid):
    """AC-1: name, description, version, rego_body accepted and persisted."""
    response = await async_client.post(
        "/v1/policies",
        json={
            "name":        POLICY_NAME,
            "description": "Default allow policy",
            "version":     POLICY_VERSION,
            "rego_body":   VALID_REGO,
        },
        headers={"Authorization": "Bearer <admin-jwt>"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["policy_group"] == POLICY_NAME
    assert body["version"]      == POLICY_VERSION
    assert body["status"]       == "draft"
    assert body["author"]       == ADMIN_AUTHOR
    assert body["rego_body"]    == VALID_REGO
```

---

### AC-2 — Previous versions retained in PostgreSQL

```python
# tests/governance/test_policy_repository.py
async def test_all_versions_retained_on_create(async_session):
    """AC-2: Creating v1.1.0 does not delete v1.0.0."""
    from src.governance.policy.repository import PolicyRepository

    repo = PolicyRepository(async_session)
    v1 = await repo.create(
        policy_group="grp", version="1.0.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )
    v2 = await repo.create(
        policy_group="grp", version="1.1.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )
    versions = await repo.list_versions("grp")
    version_strs = [r.version for r in versions]
    assert "1.0.0" in version_strs
    assert "1.1.0" in version_strs
    assert len(versions) == 2


async def test_activate_supersedes_prior_active(async_session):
    """AC-2: Activating v1.1.0 sets v1.0.0 to superseded — it is not deleted."""
    from datetime import datetime, timezone
    from src.governance.policy.repository import PolicyRepository
    from src.governance.policy.schemas    import PolicyStatus

    repo = PolicyRepository(async_session)
    v1   = await repo.create(
        policy_group="grp2", version="1.0.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v1.id, activated_at=datetime.now(tz=timezone.utc))

    v2 = await repo.create(
        policy_group="grp2", version="1.1.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v2.id, activated_at=datetime.now(tz=timezone.utc))

    versions = await repo.list_versions("grp2")
    statuses = {r.version: r.status for r in versions}
    assert statuses["1.0.0"] == PolicyStatus.SUPERSEDED
    assert statuses["1.1.0"] == PolicyStatus.ACTIVE
```

---

### AC-3 — `POST /{id}/activate` triggers OPA bundle push

```python
# tests/governance/test_policy_service.py
async def test_activate_pushes_rego_to_opa(async_session):
    """AC-3: activate() calls OPA PUT /v1/policies/{name} with the Rego body."""
    import httpx, respx
    from src.governance.policy.repository import PolicyRepository
    from src.governance.policy.service    import PolicyService
    from src.governance.policy.validator  import RegoValidator

    repo = PolicyRepository(async_session)
    record = await repo.create(
        policy_group=POLICY_NAME, version="1.0.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )

    with respx.mock(base_url="http://localhost:8181") as mock:
        # Validator PUT + DELETE
        mock.put(f"/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.delete(f"/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(200)
        )
        # Live policy push
        push_route = mock.put(f"/v1/policies/{POLICY_NAME}").mock(
            return_value=httpx.Response(200, json={})
        )

        async with httpx.AsyncClient() as client:
            svc = PolicyService(
                repository = repo,
                validator  = RegoValidator(client=client),
                opa_client = client,
            )
            resp = await svc.activate(policy_id=record.id)

    assert resp.bundle_push_ok is True
    assert push_route.called
    body_sent = push_route.calls[0].request.content.decode()
    assert "allow" in body_sent   # Rego body was transmitted
```

---

### AC-4 — Rollback restores prior version

```python
async def test_rollback_restores_previous_version(async_session):
    """AC-4: rollback to version 1.0.0 when 1.1.0 is active."""
    import httpx, respx
    from datetime import datetime, timezone
    from src.governance.policy.repository import PolicyRepository
    from src.governance.policy.service    import PolicyService
    from src.governance.policy.validator  import RegoValidator
    from src.governance.policy.schemas    import PolicyStatus

    repo = PolicyRepository(async_session)
    v1 = await repo.create(
        policy_group="grp3", version="1.0.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v1.id, activated_at=datetime.now(tz=timezone.utc))

    v2 = await repo.create(
        policy_group="grp3", version="1.1.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )
    await repo.set_active(policy_id=v2.id, activated_at=datetime.now(tz=timezone.utc))

    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.put("/v1/policies/_rego_validation_grp3").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.delete("/v1/policies/_rego_validation_grp3").mock(
            return_value=httpx.Response(200)
        )
        mock.put("/v1/policies/grp3").mock(return_value=httpx.Response(200, json={}))

        async with httpx.AsyncClient() as client:
            svc = PolicyService(
                repository = repo,
                validator  = RegoValidator(client=client),
                opa_client = client,
            )
            result = await svc.rollback(policy_group="grp3", target_version="1.0.0")

    assert result.restored_version == "1.0.0"
    assert result.previous_active  == "1.1.0"

    versions = await repo.list_versions("grp3")
    statuses  = {r.version: r.status for r in versions}
    assert statuses["1.0.0"] == PolicyStatus.ACTIVE
    assert statuses["1.1.0"] == PolicyStatus.ROLLED_BACK
```

---

### AC-5 — Author and activation timestamp recorded

```python
async def test_author_and_activated_at_stored(async_session):
    """AC-5: after activation, author is set from JWT sub and activated_at is not null."""
    import httpx, respx
    from src.governance.policy.repository import PolicyRepository
    from src.governance.policy.service    import PolicyService
    from src.governance.policy.validator  import RegoValidator

    repo   = PolicyRepository(async_session)
    record = await repo.create(
        policy_group="audit_grp", version="1.0.0",
        description="", rego_body=VALID_REGO, author=ADMIN_AUTHOR,
    )

    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.put("/v1/policies/_rego_validation_audit_grp").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.delete("/v1/policies/_rego_validation_audit_grp").mock(
            return_value=httpx.Response(200)
        )
        mock.put("/v1/policies/audit_grp").mock(
            return_value=httpx.Response(200, json={})
        )
        async with httpx.AsyncClient() as client:
            svc = PolicyService(
                repository = repo,
                validator  = RegoValidator(client=client),
                opa_client = client,
            )
            await svc.activate(policy_id=record.id)

    updated = await repo.get_by_id(record.id)
    assert updated.author       == ADMIN_AUTHOR
    assert updated.activated_at is not None
```

---

### AC-6 — Invalid Rego returns HTTP 422 with OPA parse error

```python
async def test_activate_invalid_rego_returns_422(async_client, mock_opa_invalid):
    """AC-6: OPA parse error surfaces as HTTP 422 with errors list."""
    # First create a policy with invalid Rego
    create_resp = await async_client.post(
        "/v1/policies",
        json={
            "name":      POLICY_NAME,
            "description": "",
            "version":   "0.0.1-bad",
            "rego_body": INVALID_REGO,
        },
        headers={"Authorization": "Bearer <admin-jwt>"},
    )
    assert create_resp.status_code == 201
    policy_id = create_resp.json()["id"]

    activate_resp = await async_client.post(
        f"/v1/policies/{policy_id}/activate",
        headers={"Authorization": "Bearer <admin-jwt>"},
    )
    assert activate_resp.status_code == 422
    body = activate_resp.json()
    assert "errors"   in body["detail"]
    assert len(body["detail"]["errors"]) > 0
    # Ensure the error contains parse-error messaging from OPA
    assert any("parse" in e.lower() or "error" in e.lower()
               for e in body["detail"]["errors"])


async def test_rego_validator_returns_errors_from_opa(mock_opa_invalid):
    """AC-6: RegoValidator surfaces OPA 400 errors as RegoValidationResult.errors."""
    import httpx
    from src.governance.policy.validator import RegoValidator

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client=client)
        result    = await validator.validate(POLICY_NAME, INVALID_REGO)

    assert result.is_valid is False
    assert len(result.errors) > 0
    assert "parse" in result.error_detail.lower() or "error" in result.error_detail.lower()
```

## Acceptance Criteria

- [ ] All 6 AC-level tests pass in CI without a live OPA sidecar (all OPA calls mocked via `respx`)
- [ ] `test_all_versions_retained_on_create` verifies both v1 and v2 rows exist after creating v2
- [ ] `test_activate_pushes_rego_to_opa` confirms the exact `rego_body` bytes were sent in the PUT body
- [ ] `test_rollback_restores_previous_version` checks both the returned `RollbackResponse` and the DB statuses
- [ ] `test_author_and_activated_at_stored` reads back the DB row after activation to confirm audit fields
- [ ] `test_activate_invalid_rego_returns_422` verifies the `errors` list in the 422 response is non-empty

## Dependencies

- TASK-US033-01 (`PolicyCreate`, `PolicyVersion`, `PolicyStatus`)
- TASK-US033-02 (`PolicyRepository`, `RegoValidator`, `RegoValidationError`)
- TASK-US033-03 (`PolicyService`, `PolicyVersionNotFoundError`)
- TASK-US033-04 (Admin API routes, `require_admin_role`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests mock OPA via `respx`; no live sidecar required in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
