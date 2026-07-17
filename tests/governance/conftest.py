"""Shared fixtures for governance integration tests — TASK-US031-05 / TASK-US032-05 / TASK-US033-05."""
from __future__ import annotations

import datetime as _dt
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from uuid import uuid4

# ── US033-05 shared constants ─────────────────────────────────────────────────

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


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Per-test in-memory SQLite engine with the policy_definitions table."""
    from src.governance.policy.models import PolicyRecord

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register_now_fn(dbapi_conn: object, _conn_record: object) -> None:
        assert hasattr(dbapi_conn, "create_function")
        dbapi_conn.create_function(  # type: ignore[union-attr]
            "now", 0, lambda: _dt.datetime.now(_dt.UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            PolicyRecord.__table__.metadata.create_all,
            tables=[PolicyRecord.__table__],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test AsyncSession backed by in-memory SQLite."""
    factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest.fixture
def mock_opa_valid():
    """OPA that accepts Rego (200 on PUT /v1/policies/*)."""
    import httpx
    import respx

    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.put(f"/v1/policies/{POLICY_NAME}").mock(
            return_value=httpx.Response(200, json={"result": None})
        )
        mock.delete(f"/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(200)
        )
        mock.put(f"/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(200, json={"result": None})
        )
        yield mock


@pytest.fixture
def mock_opa_invalid():
    """OPA that rejects Rego with 400 parse error."""
    import httpx
    import respx

    with respx.mock(base_url="http://localhost:8181") as mock:
        mock.put(f"/v1/policies/_rego_validation_{POLICY_NAME}").mock(
            return_value=httpx.Response(
                400,
                json={
                    "code": "invalid_parameter",
                    "message": "1 error occurred",
                    "errors": [
                        {
                            "message": (
                                "1 error occurred: rego_parse_error:"
                                " unexpected token 'error'"
                            )
                        }
                    ],
                },
            )
        )
        yield mock

CHUNK_ID = str(uuid4())

# ── US032-05 shared constants ─────────────────────────────────────────────────
SOURCE_ID  = str(uuid4())
CHUNK_A    = str(uuid4())
CHUNK_B    = str(uuid4())
TENANT_ID  = "acme"
USER_ROLES = ["developer"]

# A text block embedding one of each detectable pattern type (11 total).
SYNTHETIC_TEXT = f"""
Meeting notes — {CHUNK_ID}

Team contact: alice@contoso.com
AWS Key: AKIAIOSFODNN7EXAMPLE
AWS Secret: aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
GCP Key: AIzaSyB4example35charslongXXXXXXXXXXXXX
GitHub PAT: ghp_1234567890abcdefghijklmnopqrstuvwxyz12
Credit Card: 4111 1111 1111 1111
SSN: 123-45-6789
NI: AB123456C
Phone: +44 7700 900123
Azure: DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=dGVzdGtleXZhbHVlMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODk=
Service account: "type": "service_account"
"""


@pytest.fixture
def single_chunk() -> list[dict]:
    return [{"chunk_id": CHUNK_ID, "text": SYNTHETIC_TEXT}]


@pytest.fixture
def clean_chunk() -> list[dict]:
    return [{"chunk_id": CHUNK_ID, "text": "No secrets here. Just a normal meeting summary."}]


@pytest.fixture
def medium_only_chunk() -> list[dict]:
    return [{"chunk_id": CHUNK_ID, "text": "Call us at +44 7700 900123 for support."}]


# ── US032-05 fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def two_item_context() -> list[dict]:
    return [
        {
            "chunk_id":  CHUNK_A,
            "source_id": SOURCE_ID,
            "text":      "Public design doc content.",
            "metadata":  {"classification_label": "internal"},
        },
        {
            "chunk_id":  CHUNK_B,
            "source_id": SOURCE_ID,
            "text":      "Restricted financial data.",
            "metadata":  {"classification_label": "restricted"},
        },
    ]


@pytest.fixture
def mock_opa_allow_all():
    """OPA client that allows every chunk."""
    from unittest.mock import AsyncMock
    from src.governance.opa.schemas import PolicyDecision, AuthzFilterResult

    client = AsyncMock()

    async def _allow_batch(inputs, concurrency=10):
        decisions = [
            PolicyDecision(chunk_id=i.chunk_id, allow=True, rationale="", eval_ms=5.0)
            for i in inputs
        ]
        return AuthzFilterResult(
            decisions=decisions,
            allowed_chunk_ids=[d.chunk_id for d in decisions],
            denied_chunk_ids=[],
            total_eval_ms=10.0,
        )

    client.evaluate_batch = AsyncMock(side_effect=_allow_batch)
    return client


@pytest.fixture
def mock_opa_deny_restricted():
    """OPA client that denies chunks with classification_label='restricted'."""
    from unittest.mock import AsyncMock
    from src.governance.opa.schemas import PolicyDecision, AuthzFilterResult

    client = AsyncMock()

    async def _eval_batch(inputs, concurrency=10):
        decisions = [
            PolicyDecision(
                chunk_id=i.chunk_id,
                allow=(i.classification_label != "restricted"),
                rationale=(
                    "User roles lack access to restricted classification"
                    if i.classification_label == "restricted"
                    else ""
                ),
                eval_ms=8.0,
            )
            for i in inputs
        ]
        return AuthzFilterResult(
            decisions=decisions,
            allowed_chunk_ids=[d.chunk_id for d in decisions if d.allow],
            denied_chunk_ids=[d.chunk_id for d in decisions if d.is_denied],
            total_eval_ms=16.0,
        )

    client.evaluate_batch = AsyncMock(side_effect=_eval_batch)
    return client
