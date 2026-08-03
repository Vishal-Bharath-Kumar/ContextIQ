from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.connector_sdk.base import BaseConnector
from src.connector_sdk.registry import ConnectorRegistry
from src.connector_sdk.schemas.health import HealthStatus
from src.connector_sdk.schemas.query import ConnectorQuery
from src.connector_sdk.schemas.result import ConnectorResult
from src.connector_sdk.schemas.sync import SyncResult
from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.runtime_connectors import apply_runtime_connector_overrides


class FakeConfig:
    def __init__(self, **kwargs: object) -> None:
        self.repos = kwargs.get("repos", [])
        self.vault_path = kwargs.get("vault_path")


class FakeGitHubConnector(BaseConnector):
    def __init__(self, config: FakeConfig | None = None) -> None:
        self._config = config or FakeConfig()

    async def authenticate(self) -> None:
        return None

    async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]:
        return []

    async def sync(self) -> SyncResult:
        return SyncResult(items_processed=0, items_failed=0, last_sync_at=dt.datetime.now(dt.UTC))

    async def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True, message="ok", checked_at=dt.datetime.now(dt.UTC))


@pytest_asyncio.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register_now_fn(dbapi_conn: object, _: object) -> None:
        assert hasattr(dbapi_conn, "create_function")
        dbapi_conn.create_function(  # type: ignore[union-attr]
            "now", 0, lambda: dt.datetime.now(dt.UTC).isoformat()
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            KnowledgeSourceRecord.__table__.metadata.create_all,
            tables=[KnowledgeSourceRecord.__table__],
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(async_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_apply_runtime_connector_overrides_aggregates_active_scopes_same_vault_path(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                KnowledgeSourceRecord(
                    name="Expense Tracker",
                    connector_type="github",
                    credentials_vault_path="connectors/github/my-org-pat",
                    scope="Vishal-Bharath-Kumar/Expense-Tracker",
                    is_active=True,
                ),
                KnowledgeSourceRecord(
                    name="ContextIQ",
                    connector_type="github",
                    credentials_vault_path="connectors/github/my-org-pat",
                    scope="Vishal-Bharath-Kumar/ContextIQ",
                    is_active=True,
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(
        "src.knowledge_sources.runtime_connectors.CONNECTOR_CLASS_MAP",
        {"github": (FakeGitHubConnector, FakeConfig)},
    )

    registry = ConnectorRegistry()
    await apply_runtime_connector_overrides(registry, session_factory)

    connector = registry.get("github")

    assert connector is not None
    assert isinstance(connector, FakeGitHubConnector)
    assert connector._config.vault_path == "connectors/github/my-org-pat"
    assert connector._config.repos == [
        "Vishal-Bharath-Kumar/Expense-Tracker",
        "Vishal-Bharath-Kumar/ContextIQ",
    ]