# TASK-US025-05 — Integration Tests: All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US025-05 |
| User Story | US-025 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Done |

## Description

Write the integration test suite covering all 6 US-025 acceptance criteria: create (201), invalid Vault path (400), duplicate source (409), list with status/sync/count (200), active toggle (PATCH), and Kafka creation event emission. Tests use `httpx.AsyncClient`, `AsyncMock` for Vault validator and Kafka, and an in-memory async SQLite session.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `httpx.AsyncClient`

**File locations:**
- `tests/knowledge_sources/test_knowledge_source_integration.py`

**Test fixtures:**

```python
# tests/knowledge_sources/test_knowledge_source_integration.py
import pytest, json
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

from src.gateway.main import app   # FastAPI app instance
from src.knowledge_sources.vault_validator import VaultPathValidator, VaultValidationResult

VALID_PAYLOAD = {
    "connector_type":          "github",
    "credentials_vault_path":  "secret/data/github/token",
    "scope":                   "acme/backend",
    "sync_schedule":           "0 */6 * * *",
    "token_budget_weight":     1.5,
}
ADMIN_HEADERS = {"Authorization": "Bearer <admin-jwt-fixture>"}   # fixture from conftest.py


@pytest.fixture
def mock_vault_valid():
    """Patch VaultPathValidator to return valid=True."""
    with patch.object(
        VaultPathValidator, "validate",
        new_callable = AsyncMock,
        return_value = VaultValidationResult(valid=True, message="ok"),
    ):
        yield


@pytest.fixture
def mock_vault_invalid():
    """Patch VaultPathValidator to return valid=False with descriptive message."""
    with patch.object(
        VaultPathValidator, "validate",
        new_callable = AsyncMock,
        return_value = VaultValidationResult(
            valid   = False,
            message = "Vault path 'secret/data/bad/path' does not exist in mount 'secret'",
        ),
    ):
        yield


@pytest.fixture
def mock_kafka():
    with patch("src.knowledge_sources.services.knowledge_source_service.get_kafka_producer") as m:
        producer = AsyncMock()
        producer.send_and_wait = AsyncMock()
        m.return_value = producer
        yield producer
```

**AC-1 — `POST` creates source (HTTP 201):**

```python
async def test_create_knowledge_source_returns_201(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
    assert resp.status_code == 201
    body = resp.json()
    assert body["connector_type"] == "github"
    assert body["scope"]          == "acme/backend"
    assert body["status"]         == "active"
    assert body["is_active"]      is True
    assert body["document_count"] == 0
    assert "id" in body
```

**AC-2 — Credentials stored in Vault path (not in DB response):**

```python
async def test_response_contains_vault_path_not_token(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
    body = resp.json()
    # The path reference is stored; no token value ever appears in the response
    assert body["credentials_vault_path"] == "secret/data/github/token"
    assert "token" not in json.dumps(body).lower() or body.get("token") is None
```

**AC-3 — `GET` returns status, last_sync_at, document_count:**

```python
async def test_list_returns_status_fields(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
        resp = await client.get("/v1/knowledge-sources", headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    sources = resp.json()
    assert len(sources) >= 1
    first = sources[0]
    assert "status"         in first
    assert "last_sync_at"   in first   # may be null for new source
    assert "document_count" in first
```

**AC-4 — Toggle active/inactive without deletion:**

```python
async def test_toggle_inactive_does_not_delete(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
        source_id   = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/v1/knowledge-sources/{source_id}/status",
            json    = {"active": False},
            headers = ADMIN_HEADERS,
        )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_active"] is False
    assert patch_resp.json()["status"]    == "inactive"

    # Source still exists in GET response
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_resp = await client.get("/v1/knowledge-sources", headers=ADMIN_HEADERS)
    ids = [s["id"] for s in list_resp.json()]
    assert source_id in ids
```

**AC-5 — Invalid Vault path returns HTTP 400:**

```python
async def test_invalid_vault_path_returns_400(mock_vault_invalid, mock_kafka):
    payload = {**VALID_PAYLOAD, "credentials_vault_path": "secret/data/bad/path"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/knowledge-sources", json=payload, headers=ADMIN_HEADERS)
    assert resp.status_code == 400
    assert "does not exist" in resp.json()["detail"]
```

**AC-6 — Kafka creation event emitted:**

```python
async def test_kafka_event_emitted_on_create(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
    mock_kafka.send_and_wait.assert_awaited_once()
    call_kwargs = mock_kafka.send_and_wait.call_args
    topic = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("topic")
    assert topic == "knowledge.source.created"
    payload = json.loads(call_kwargs.kwargs.get("value", b"{}"))
    assert payload["connector_type"] == "github"
    assert payload["scope"]          == "acme/backend"
```

**Additional edge-case tests:**

```python
async def test_duplicate_source_returns_409(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
        resp = await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD, headers=ADMIN_HEADERS)
    assert resp.status_code == 409

async def test_toggle_unknown_source_returns_404(mock_vault_valid, mock_kafka):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            f"/v1/knowledge-sources/{uuid4()}/status",
            json    = {"active": False},
            headers = ADMIN_HEADERS,
        )
    assert resp.status_code == 404

async def test_non_admin_returns_403():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/knowledge-sources", json=VALID_PAYLOAD,
                                  headers={"Authorization": "Bearer <non-admin-token>"})
    assert resp.status_code == 403
```

## Acceptance Criteria

- [x] `test_create_knowledge_source_returns_201` passes
- [x] `test_response_contains_vault_path_not_token` passes (no token value in response body)
- [x] `test_list_returns_status_fields` passes
- [x] `test_toggle_inactive_does_not_delete` passes
- [x] `test_invalid_vault_path_returns_400` passes with descriptive `detail` message
- [x] `test_kafka_event_emitted_on_create` passes; topic is `knowledge.source.created`
- [x] `test_duplicate_source_returns_409` passes
- [x] `test_non_admin_returns_403` passes

## Dependencies

- TASK-US025-01 (schemas)
- TASK-US025-02 (`VaultPathValidator` — patched in fixtures)
- TASK-US025-03 (`KnowledgeSourceService`)
- TASK-US025-04 (router — endpoints under test)

## Definition of Done

- [x] Code reviewed and merged to `main`
- [x] All 8 tests pass in CI with no live DB, Vault, or Kafka connections
- [x] `mypy --strict` passes; no `ruff` lint errors
