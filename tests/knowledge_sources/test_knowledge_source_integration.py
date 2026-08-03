"""Integration tests for Knowledge Source Admin API — TASK-US025-05.

Tests exercise the full request→service→repository→DB round-trip using:
- ``httpx.AsyncClient`` with an ASGITransport pointing at the real FastAPI app
- An in-memory async SQLite engine (``aiosqlite``) injected via ``get_db``
  dependency override — no PostgreSQL connection required
- ``AsyncMock`` patches for VaultPathValidator and the Kafka producer so no
  external services are needed

Acceptance criteria covered (US-025):
  AC-1  POST creates source (HTTP 201) with correct response body
  AC-2  Vault path reference stored; token value never appears in response
  AC-3  GET returns sources with status, last_sync_at, document_count fields
  AC-4  PATCH /{id}/status toggles is_active/status without deleting the record
  AC-5  POST with invalid Vault path returns HTTP 400 with descriptive detail
  AC-6  POST emits Kafka event on topic "knowledge.source.created"

Additional edge cases:
  AC-7  POST with duplicate (connector_type, scope) returns HTTP 409
  AC-8  PATCH on unknown source_id returns HTTP 404
  AC-9  Non-admin request returns HTTP 403
"""
from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.auth.dependencies import decode_jwt_claims
from src.auth.roles import PlatformRole
from src.auth.testing import make_test_claims
from src.data.dependencies import get_db
from src.knowledge_sources.models.connector_audit_log import ConnectorAuditLog
from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.vault_validator import VaultPathValidator, VaultValidationResult
from src.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PAYLOAD: dict[str, object] = {
    "name": "Acme Backend",
    "connector_type": "github",
    "credentials_vault_path": "secret/data/github/token",
    "scope": "acme/backend",
    "sync_schedule": "0 */6 * * *",
    "token_budget_weight": 1.5,
}

_ADMIN_CLAIMS = make_test_claims(PlatformRole.ADMIN)
_DEVELOPER_CLAIMS = make_test_claims(PlatformRole.DEVELOPER)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Per-test in-memory SQLite engine with the knowledge_sources table.

    Registers a ``now()`` UDF so that ``server_default=text("now()")`` columns
    on KnowledgeSourceRecord resolve correctly under SQLite.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register_now_fn(dbapi_conn: object, _conn_record: object) -> None:
        assert hasattr(dbapi_conn, "create_function")
        dbapi_conn.create_function(
            "now", 0, lambda: dt.datetime.now(dt.UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            KnowledgeSourceRecord.__table__.metadata.create_all,
            tables=[KnowledgeSourceRecord.__table__, ConnectorAuditLog.__table__],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory backed by the in-memory SQLite engine."""
    return async_sessionmaker(async_engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Vault / Kafka mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_vault_valid() -> Iterator[None]:
    """Patch VaultPathValidator.validate to return valid=True."""
    with patch.object(
        VaultPathValidator,
        "validate",
        new_callable=AsyncMock,
        return_value=VaultValidationResult(valid=True, message="ok"),
    ):
        yield


@pytest.fixture
def mock_vault_invalid() -> Iterator[None]:
    """Patch VaultPathValidator.validate to return valid=False."""
    with patch.object(
        VaultPathValidator,
        "validate",
        new_callable=AsyncMock,
        return_value=VaultValidationResult(
            valid=False,
            message="Vault path 'secret/data/bad/path' does not exist in mount 'secret'",
        ),
    ):
        yield


@pytest.fixture
def mock_kafka() -> Iterator[AsyncMock]:
    """Patch get_kafka_producer in src.events.producer with an AsyncMock."""
    with patch("src.events.producer.get_kafka_producer") as m:
        producer = AsyncMock()
        producer.send_and_wait = AsyncMock()
        m.return_value = producer
        yield producer


# ---------------------------------------------------------------------------
# Shared client fixture (admin, mocked vault valid, mocked kafka, SQLite DB)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_client(
    db_session_factory: async_sessionmaker[AsyncSession],
    mock_vault_valid: None,
    mock_kafka: AsyncMock,
) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient pre-configured with:
    - Admin JWT claims (via decode_jwt_claims override)
    - In-memory SQLite session (via get_db override)
    - VaultPathValidator always returns valid=True
    - Kafka producer mocked
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(decode_jwt_claims, None)


# ---------------------------------------------------------------------------
# AC-1 — POST creates source (HTTP 201)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_knowledge_source_returns_201(
    admin_client: AsyncClient,
) -> None:
    """AC-1: POST with valid payload returns 201 and a well-formed response body."""
    resp = await admin_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)

    assert resp.status_code == 201
    body = resp.json()
    assert body["connector_type"] == "github"
    assert body["scope"] == "acme/backend"
    assert body["status"] == "active"
    assert body["is_active"] is True
    assert body["document_count"] == 0
    assert "id" in body


# ---------------------------------------------------------------------------
# AC-2 — Vault path stored; token value never in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_contains_vault_path_not_token(
    admin_client: AsyncClient,
) -> None:
    """AC-2: Response carries the vault path reference; no credential value appears."""
    resp = await admin_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)

    assert resp.status_code == 201
    body = resp.json()
    assert body["credentials_vault_path"] == "secret/data/github/token"
    # Ensure no raw token value is serialised into the response
    response_text = json.dumps(body).lower()
    assert "bearer" not in response_text
    assert body.get("token") is None
    assert body.get("secret") is None


# ---------------------------------------------------------------------------
# AC-3 — GET returns status, last_sync_at, document_count fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_status_fields(
    admin_client: AsyncClient,
) -> None:
    """AC-3: GET /v1/knowledge-sources returns required status/sync/count fields."""
    await admin_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)

    resp = await admin_client.get("/v1/knowledge-sources")

    assert resp.status_code == 200
    sources = resp.json()
    assert len(sources) >= 1
    first = sources[0]
    assert "status" in first
    assert "last_sync_at" in first  # may be null for a new source
    assert "document_count" in first


# ---------------------------------------------------------------------------
# AC-4 — Toggle active/inactive without deletion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_inactive_does_not_delete(
    admin_client: AsyncClient,
) -> None:
    """AC-4: PATCH sets is_active=False/status=inactive; record survives in GET."""
    create_resp = await admin_client.post(
        "/v1/knowledge-sources", json=VALID_PAYLOAD
    )
    assert create_resp.status_code == 201
    source_id = create_resp.json()["id"]

    patch_resp = await admin_client.patch(
        f"/v1/knowledge-sources/{source_id}/status",
        json={"active": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["is_active"] is False
    assert patch_resp.json()["status"] == "inactive"

    # Source still returned by the list endpoint
    list_resp = await admin_client.get("/v1/knowledge-sources")
    assert list_resp.status_code == 200
    ids = [s["id"] for s in list_resp.json()]
    assert source_id in ids


# ---------------------------------------------------------------------------
# AC-5 — Invalid Vault path → HTTP 400
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def invalid_vault_client(
    db_session_factory: async_sessionmaker[AsyncSession],
    mock_vault_invalid: None,
    mock_kafka: AsyncMock,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with admin claims and a vault validator that always fails."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[decode_jwt_claims] = lambda: _ADMIN_CLAIMS

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(decode_jwt_claims, None)


@pytest_asyncio.fixture
async def developer_client(
    db_session_factory: async_sessionmaker[AsyncSession],
    mock_vault_valid: None,
    mock_kafka: AsyncMock,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with developer (non-admin) claims for 403 tests."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[decode_jwt_claims] = lambda: _DEVELOPER_CLAIMS

    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(decode_jwt_claims, None)


@pytest.mark.asyncio
async def test_invalid_vault_path_returns_400(
    invalid_vault_client: AsyncClient,
) -> None:
    """AC-5: POST with a bad Vault path returns 400 with a descriptive detail."""
    payload = {**VALID_PAYLOAD, "credentials_vault_path": "secret/data/bad/path"}
    resp = await invalid_vault_client.post("/v1/knowledge-sources", json=payload)

    assert resp.status_code == 400
    assert "does not exist" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# AC-6 — Kafka creation event emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kafka_event_emitted_on_create(
    admin_client: AsyncClient,
    mock_kafka: AsyncMock,
) -> None:
    """AC-6: Creating a source emits exactly one event on 'knowledge.source.created'."""
    await admin_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)

    mock_kafka.send_and_wait.assert_awaited_once()

    call_args = mock_kafka.send_and_wait.call_args
    topic = (
        call_args.args[0]
        if call_args.args
        else call_args.kwargs.get("topic")
    )
    assert topic == "knowledge.source.created"

    raw_value: bytes = (
        call_args.args[1]
        if len(call_args.args) > 1
        else call_args.kwargs.get("value", b"{}")
    )
    event_payload = json.loads(raw_value)
    assert event_payload["connector_type"] == "github"
    assert event_payload["scope"] == "acme/backend"


# ---------------------------------------------------------------------------
# AC-7 — Duplicate (connector_type, scope) → HTTP 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_source_returns_409(
    admin_client: AsyncClient,
) -> None:
    """AC-7: Second POST with same connector_type+scope returns 409."""
    first = await admin_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)
    assert first.status_code == 201

    second = await admin_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# AC-8 — PATCH on unknown source_id → HTTP 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toggle_unknown_source_returns_404(
    admin_client: AsyncClient,
) -> None:
    """AC-8: PATCH on a non-existent source_id returns 404."""
    resp = await admin_client.patch(
        f"/v1/knowledge-sources/{uuid4()}/status",
        json={"active": False},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-9 — Non-admin request → HTTP 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_admin_returns_403(
    developer_client: AsyncClient,
) -> None:
    """AC-9: A request with non-admin claims is rejected with HTTP 403."""
    resp = await developer_client.post("/v1/knowledge-sources", json=VALID_PAYLOAD)
    assert resp.status_code == 403
