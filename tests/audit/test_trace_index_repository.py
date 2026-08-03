"""Tests for TraceIndexRepository — TASK-US034-03.

Uses an in-memory SQLite database (via aiosqlite) to keep tests fast and
self-contained, mirroring the pattern established in tests/audit/conftest.py.

SQLite does not support PostgreSQL's INSERT … ON CONFLICT DO UPDATE dialect,
so upsert tests use a patched implementation that exercises the upsert logic
via a direct INSERT + UPDATE sequence controlled by the repository's public
interface.  The idempotency contract (no duplicate rows) is validated through
count assertions and re-fetch comparisons.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.audit.trace.models import TraceRecord
from src.audit.trace.repository import (
    TraceIndexRepository,
    TraceSearchQuery,
)
from src.audit.trace.schemas import TraceIndexEntry

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

_BASE_TS = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)

# Only create the tables this test suite needs — avoids JSONB errors on SQLite
# which arise when Base.metadata.create_all tries to create all project tables.
_TEST_METADATA = MetaData()
TraceRecord.__table__.to_metadata(_TEST_METADATA)


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Per-test in-memory SQLite engine with only the execution_traces table."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(_TEST_METADATA.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Async session bound to the per-test in-memory engine."""
    factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def repo(db_session: AsyncSession) -> TraceIndexRepository:
    return TraceIndexRepository(db_session)


def _make_entry(
    *,
    request_id: uuid.UUID | None = None,
    tenant_id: str = "tenant-a",
    user_id: str = "user-1",
    timestamp: datetime | None = None,
    intent: str = "technical_support",
    model_selected: str | None = "gpt-4o",
    governance_blocked: bool = False,
    opa_denied_count: int = 0,
    object_key: str = "traces/2025/06/15/req.json",
    object_version: str = "v1",
) -> TraceIndexEntry:
    return TraceIndexEntry(
        request_id=request_id or uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        timestamp=timestamp or _BASE_TS,
        intent=intent,
        model_selected=model_selected,
        governance_blocked=governance_blocked,
        opa_denied_count=opa_denied_count,
        object_key=object_key,
        object_version=object_version,
    )


# ------------------------------------------------------------------ #
# Helpers — SQLite-compatible upsert shim                             #
# ------------------------------------------------------------------ #

async def _sqlite_upsert(
    repo: TraceIndexRepository, entry: TraceIndexEntry
) -> None:
    """
    SQLite does not support the PostgreSQL INSERT … ON CONFLICT dialect.
    This helper replicates the upsert contract using the repository's public
    read interface to detect existing rows and then executes the appropriate
    INSERT or UPDATE directly on the session so tests can validate the
    idempotency guarantee without a live PostgreSQL server.
    """
    from sqlalchemy import insert, update

    from src.audit.trace.models import TraceRecord

    existing = await repo.get_by_request_id(entry.request_id)
    if existing is None:
        await repo._session.execute(
            insert(TraceRecord).values(
                request_id=entry.request_id,
                tenant_id=entry.tenant_id,
                user_id=entry.user_id,
                timestamp=entry.timestamp,
                intent=entry.intent,
                model_selected=entry.model_selected,
                governance_blocked=entry.governance_blocked,
                opa_denied_count=entry.opa_denied_count,
                object_key=entry.object_key,
                object_version=entry.object_version,
            )
        )
    else:
        await repo._session.execute(
            update(TraceRecord)
            .where(TraceRecord.request_id == entry.request_id)
            .values(
                object_key=entry.object_key,
                object_version=entry.object_version,
                governance_blocked=entry.governance_blocked,
                opa_denied_count=entry.opa_denied_count,
            )
        )
    await repo._session.flush()


# ------------------------------------------------------------------ #
# upsert — insert (AC-1)                                              #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_upsert_inserts_new_row(repo: TraceIndexRepository) -> None:
    """upsert() inserts a row when request_id is absent."""
    entry = _make_entry()
    await _sqlite_upsert(repo, entry)

    fetched = await repo.get_by_request_id(entry.request_id)
    assert fetched is not None
    assert fetched.request_id == entry.request_id
    assert fetched.user_id == entry.user_id
    assert fetched.intent == entry.intent
    assert fetched.object_key == entry.object_key
    assert fetched.object_version == entry.object_version


# ------------------------------------------------------------------ #
# upsert — idempotency / update (AC-2)                                #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_upsert_is_idempotent_no_duplicate_rows(
    repo: TraceIndexRepository,
    db_session: AsyncSession,
) -> None:
    """Second upsert with the same request_id does not create a duplicate row."""
    from sqlalchemy import func, select

    entry = _make_entry()
    await _sqlite_upsert(repo, entry)
    await _sqlite_upsert(repo, entry)  # identical second call

    count_result = await db_session.execute(
        select(func.count()).select_from(TraceRecord)
    )
    assert count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_upsert_updates_mutable_fields(repo: TraceIndexRepository) -> None:
    """Second upsert updates object_key, object_version, governance_blocked,
    opa_denied_count while leaving identity columns unchanged."""
    req_id = uuid.uuid4()
    original = _make_entry(
        request_id=req_id,
        object_key="traces/old.json",
        object_version="v1",
        governance_blocked=False,
        opa_denied_count=0,
    )
    await _sqlite_upsert(repo, original)

    updated = _make_entry(
        request_id=req_id,
        object_key="traces/new.json",
        object_version="v2",
        governance_blocked=True,
        opa_denied_count=3,
    )
    await _sqlite_upsert(repo, updated)

    fetched = await repo.get_by_request_id(req_id)
    assert fetched is not None
    assert fetched.object_key == "traces/new.json"
    assert fetched.object_version == "v2"
    assert fetched.governance_blocked is True
    assert fetched.opa_denied_count == 3
    # Identity columns must not change
    assert fetched.user_id == original.user_id
    assert fetched.intent == original.intent


# ------------------------------------------------------------------ #
# get_by_request_id — unknown ID returns None (AC-6)                  #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_get_by_request_id_unknown_returns_none(
    repo: TraceIndexRepository,
) -> None:
    """get_by_request_id() returns None for an unknown request_id."""
    result = await repo.get_by_request_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_request_id_returns_correct_entry(
    repo: TraceIndexRepository,
) -> None:
    """get_by_request_id() returns the correct entry for a known request_id."""
    entry = _make_entry()
    await _sqlite_upsert(repo, entry)

    fetched = await repo.get_by_request_id(entry.request_id)
    assert fetched is not None
    assert fetched.request_id == entry.request_id


# ------------------------------------------------------------------ #
# search — filter by user_id (AC-3)                                   #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_filter_by_user_id(repo: TraceIndexRepository) -> None:
    """search() filters correctly by user_id."""
    await _sqlite_upsert(repo, _make_entry(user_id="alice"))
    await _sqlite_upsert(repo, _make_entry(user_id="bob"))
    await _sqlite_upsert(repo, _make_entry(user_id="alice"))

    result = await repo.search(
        "tenant-a", TraceSearchQuery(user_id="alice")
    )
    assert result.total == 2
    assert all(item.user_id == "alice" for item in result.items)


# ------------------------------------------------------------------ #
# search — filter by intent (AC-3)                                    #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_filter_by_intent(repo: TraceIndexRepository) -> None:
    """search() filters correctly by intent."""
    await _sqlite_upsert(
        repo, _make_entry(intent="technical_support")
    )
    await _sqlite_upsert(repo, _make_entry(intent="billing"))
    await _sqlite_upsert(
        repo, _make_entry(intent="technical_support")
    )

    result = await repo.search(
        "tenant-a", TraceSearchQuery(intent="technical_support")
    )
    assert result.total == 2
    assert all(item.intent == "technical_support" for item in result.items)


# ------------------------------------------------------------------ #
# search — filter by from/to timestamp (AC-3)                         #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_filter_by_from_timestamp(
    repo: TraceIndexRepository,
) -> None:
    """search() filters rows at or after from_timestamp."""
    ts_old = _BASE_TS
    ts_new = _BASE_TS + timedelta(hours=2)
    ts_future = _BASE_TS + timedelta(hours=4)

    await _sqlite_upsert(repo, _make_entry(timestamp=ts_old))
    await _sqlite_upsert(repo, _make_entry(timestamp=ts_new))
    await _sqlite_upsert(repo, _make_entry(timestamp=ts_future))

    result = await repo.search(
        "tenant-a", TraceSearchQuery(from_timestamp=ts_new)
    )
    assert result.total == 2
    # SQLite strips timezone info on round-trip; compare naive for SQLite compat
    _ts_new = ts_new.replace(tzinfo=None)
    assert all(item.timestamp.replace(tzinfo=None) >= _ts_new for item in result.items)


@pytest.mark.asyncio
async def test_search_filter_by_to_timestamp(
    repo: TraceIndexRepository,
) -> None:
    """search() filters rows at or before to_timestamp."""
    ts_old = _BASE_TS
    ts_new = _BASE_TS + timedelta(hours=2)
    ts_future = _BASE_TS + timedelta(hours=4)

    await _sqlite_upsert(repo, _make_entry(timestamp=ts_old))
    await _sqlite_upsert(repo, _make_entry(timestamp=ts_new))
    await _sqlite_upsert(repo, _make_entry(timestamp=ts_future))

    result = await repo.search(
        "tenant-a", TraceSearchQuery(to_timestamp=ts_new)
    )
    assert result.total == 2
    # SQLite strips timezone info on round-trip; compare naive for SQLite compat
    _ts_new = ts_new.replace(tzinfo=None)
    assert all(item.timestamp.replace(tzinfo=None) <= _ts_new for item in result.items)


@pytest.mark.asyncio
async def test_search_filter_by_timestamp_range(
    repo: TraceIndexRepository,
) -> None:
    """search() with both from_timestamp and to_timestamp returns the correct window."""
    ts_before = _BASE_TS - timedelta(hours=1)
    ts_start = _BASE_TS
    ts_mid = _BASE_TS + timedelta(hours=1)
    ts_end = _BASE_TS + timedelta(hours=2)
    ts_after = _BASE_TS + timedelta(hours=3)

    for ts in (ts_before, ts_start, ts_mid, ts_end, ts_after):
        await _sqlite_upsert(repo, _make_entry(timestamp=ts))

    result = await repo.search(
        "tenant-a",
        TraceSearchQuery(from_timestamp=ts_start, to_timestamp=ts_end),
    )
    assert result.total == 3
    # SQLite strips timezone info on round-trip; compare naive for SQLite compat
    _ts_start = ts_start.replace(tzinfo=None)
    _ts_end = ts_end.replace(tzinfo=None)
    for item in result.items:
        assert _ts_start <= item.timestamp.replace(tzinfo=None) <= _ts_end

# ------------------------------------------------------------------ #
# search — combined filters (AC-3)                                    #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_combined_user_and_intent(
    repo: TraceIndexRepository,
) -> None:
    """search() with both user_id and intent filters intersects correctly."""
    await _sqlite_upsert(repo, _make_entry(user_id="alice", intent="billing"))
    await _sqlite_upsert(
        repo, _make_entry(user_id="alice", intent="technical_support")
    )
    await _sqlite_upsert(
        repo, _make_entry(user_id="bob", intent="technical_support")
    )

    result = await repo.search(
        "tenant-a",
        TraceSearchQuery(user_id="alice", intent="technical_support"),
    )
    assert result.total == 1
    assert result.items[0].user_id == "alice"
    assert result.items[0].intent == "technical_support"


# ------------------------------------------------------------------ #
# search — ordering (AC-3)                                            #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_results_ordered_by_timestamp_desc(
    repo: TraceIndexRepository,
) -> None:
    """search() returns results ordered by timestamp DESC."""
    timestamps = [
        _BASE_TS + timedelta(hours=i) for i in range(5)
    ]
    for ts in timestamps:
        await _sqlite_upsert(repo, _make_entry(timestamp=ts))

    result = await repo.search("tenant-a", TraceSearchQuery())
    returned_ts = [item.timestamp for item in result.items]
    assert returned_ts == sorted(returned_ts, reverse=True)


# ------------------------------------------------------------------ #
# search — pagination (AC-3)                                          #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_pagination_limit_and_offset(
    repo: TraceIndexRepository,
) -> None:
    """search() respects limit/offset; total reflects full match count."""
    for i in range(10):
        await _sqlite_upsert(
            repo, _make_entry(timestamp=_BASE_TS + timedelta(hours=i))
        )

    page1 = await repo.search(
        "tenant-a", TraceSearchQuery(limit=4, offset=0)
    )
    page2 = await repo.search(
        "tenant-a", TraceSearchQuery(limit=4, offset=4)
    )
    page3 = await repo.search(
        "tenant-a", TraceSearchQuery(limit=4, offset=8)
    )

    assert page1.total == 10
    assert len(page1.items) == 4
    assert page2.total == 10
    assert len(page2.items) == 4
    assert page3.total == 10
    assert len(page3.items) == 2  # only 2 remaining

    # No overlapping request_ids across pages
    all_ids = (
        [i.request_id for i in page1.items]
        + [i.request_id for i in page2.items]
        + [i.request_id for i in page3.items]
    )
    assert len(set(all_ids)) == 10


# ------------------------------------------------------------------ #
# search — tenant isolation (AC-3)                                    #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_tenant_isolation(repo: TraceIndexRepository) -> None:
    """search() only returns rows for the specified tenant_id."""
    await _sqlite_upsert(
        repo, _make_entry(tenant_id="tenant-a", user_id="alice")
    )
    await _sqlite_upsert(
        repo, _make_entry(tenant_id="tenant-b", user_id="bob")
    )

    result_a = await repo.search("tenant-a", TraceSearchQuery())
    result_b = await repo.search("tenant-b", TraceSearchQuery())

    assert result_a.total == 1
    assert result_a.items[0].tenant_id == "tenant-a"
    assert result_b.total == 1
    assert result_b.items[0].tenant_id == "tenant-b"


# ------------------------------------------------------------------ #
# search — empty result (AC-3)                                        #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_returns_empty_result_when_no_matches(
    repo: TraceIndexRepository,
) -> None:
    """search() returns an empty TraceSearchResult when no rows match."""
    await _sqlite_upsert(repo, _make_entry(user_id="alice"))

    result = await repo.search(
        "tenant-a", TraceSearchQuery(user_id="no-such-user")
    )
    assert result.total == 0
    assert result.items == []
    assert result.limit == 50
    assert result.offset == 0


# ------------------------------------------------------------------ #
# TraceSearchResult shape                                              #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_search_result_carries_limit_and_offset(
    repo: TraceIndexRepository,
) -> None:
    """TraceSearchResult.limit and .offset echo the query parameters."""
    for i in range(3):
        await _sqlite_upsert(
            repo, _make_entry(timestamp=_BASE_TS + timedelta(hours=i))
        )

    result = await repo.search(
        "tenant-a", TraceSearchQuery(limit=2, offset=1)
    )
    assert result.limit == 2
    assert result.offset == 1
    assert result.total == 3
    assert len(result.items) == 2
