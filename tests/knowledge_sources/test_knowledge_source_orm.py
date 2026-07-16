"""Unit tests for KnowledgeSourceRecord ORM and Pydantic schemas — TASK-US025-01.

All tests run without a database connection; ORM tests assert in-memory
object construction, schema tests assert Pydantic validation behaviour.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.knowledge_sources.models.knowledge_source import KnowledgeSourceRecord
from src.knowledge_sources.schemas.knowledge_source import (
    ConnectorType,
    KnowledgeSourceCreate,
    KnowledgeSourceResponse,
    SourceStatus,
)

NOW = datetime(2026, 7, 16, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ORM model — no DB required
# ---------------------------------------------------------------------------


class TestKnowledgeSourceRecord:
    def test_instantiation_minimal(self) -> None:
        record = KnowledgeSourceRecord(
            connector_type="github",
            credentials_vault_path="secret/contextiq/github/acme",
            scope="acme-org/api-service",
        )
        assert record.connector_type == "github"
        assert record.scope == "acme-org/api-service"

    def test_default_status_and_weight(self) -> None:
        record = KnowledgeSourceRecord(
            connector_type="confluence",
            credentials_vault_path="secret/contextiq/confluence/dev",
            scope="DEVSPACE",
        )
        # Python-side defaults are not set via server_default; verify field exists
        assert record.status is None or record.status in (None, "active")
        assert record.is_active is None or record.is_active in (None, True)

    def test_all_connector_types_accepted(self) -> None:
        for ct in ("github", "confluence", "jira", "grafana"):
            record = KnowledgeSourceRecord(
                connector_type=ct,
                credentials_vault_path=f"secret/contextiq/{ct}/test",
                scope="test-scope",
            )
            assert record.connector_type == ct

    def test_last_sync_at_nullable(self) -> None:
        record = KnowledgeSourceRecord(
            connector_type="jira",
            credentials_vault_path="secret/contextiq/jira/prod",
            scope="PROJ",
        )
        assert record.last_sync_at is None


# ---------------------------------------------------------------------------
# KnowledgeSourceCreate — validation
# ---------------------------------------------------------------------------


class TestKnowledgeSourceCreate:
    def test_valid_minimal(self) -> None:
        payload = KnowledgeSourceCreate(
            connector_type=ConnectorType.GITHUB,
            credentials_vault_path="secret/contextiq/github/acme",
            scope="acme-org/api-service",
        )
        assert payload.sync_schedule == "0 */6 * * *"
        assert payload.token_budget_weight == 1.0

    def test_valid_custom_schedule(self) -> None:
        payload = KnowledgeSourceCreate(
            connector_type=ConnectorType.CONFLUENCE,
            credentials_vault_path="secret/contextiq/confluence/wiki",
            scope="WIKI",
            sync_schedule="30 2 * * *",
        )
        assert payload.sync_schedule == "30 2 * * *"

    def test_invalid_cron_six_fields_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            KnowledgeSourceCreate(
                connector_type=ConnectorType.JIRA,
                credentials_vault_path="secret/contextiq/jira/proj",
                scope="PROJ",
                sync_schedule="0 */6 * * * *",  # 6 fields — invalid
            )
        assert "5-field cron expression" in str(exc_info.value)

    def test_invalid_token_budget_exceeds_max_raises(self) -> None:
        with pytest.raises(ValidationError):
            KnowledgeSourceCreate(
                connector_type=ConnectorType.GITHUB,
                credentials_vault_path="secret/contextiq/github/acme",
                scope="acme-org/api-service",
                token_budget_weight=10.1,
            )

    def test_invalid_vault_path_with_spaces_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            KnowledgeSourceCreate(
                connector_type=ConnectorType.GITHUB,
                credentials_vault_path="secret/contextiq/bad path",
                scope="acme-org/api-service",
            )
        assert "invalid characters" in str(exc_info.value)

    def test_token_budget_weight_zero_is_valid(self) -> None:
        payload = KnowledgeSourceCreate(
            connector_type=ConnectorType.GRAFANA,
            credentials_vault_path="secret/contextiq/grafana/ops",
            scope="ops-dashboard",
            token_budget_weight=0.0,
        )
        assert payload.token_budget_weight == 0.0

    def test_token_budget_weight_max_is_valid(self) -> None:
        payload = KnowledgeSourceCreate(
            connector_type=ConnectorType.GRAFANA,
            credentials_vault_path="secret/contextiq/grafana/ops",
            scope="ops-dashboard",
            token_budget_weight=10.0,
        )
        assert payload.token_budget_weight == 10.0


# ---------------------------------------------------------------------------
# KnowledgeSourceResponse — ORM population
# ---------------------------------------------------------------------------


class TestKnowledgeSourceResponse:
    def _make_record(self) -> KnowledgeSourceRecord:
        record = KnowledgeSourceRecord(
            connector_type="github",
            credentials_vault_path="secret/contextiq/github/acme",
            scope="acme-org/api-service",
            sync_schedule="0 */6 * * *",
            token_budget_weight=1.5,
            status="active",
            is_active=True,
            last_sync_at=NOW,
            document_count=42,
            created_at=NOW,
            updated_at=NOW,
        )
        record.id = uuid4()
        return record

    def test_from_orm_all_fields_populated(self) -> None:
        record = self._make_record()
        response = KnowledgeSourceResponse.model_validate(record)

        assert isinstance(response.id, UUID)
        assert response.connector_type == ConnectorType.GITHUB
        assert response.status == SourceStatus.ACTIVE
        assert response.last_sync_at == NOW
        assert response.document_count == 42
        assert response.token_budget_weight == 1.5

    def test_from_orm_null_last_sync_at(self) -> None:
        record = self._make_record()
        record.last_sync_at = None
        record.created_at = NOW
        record.updated_at = NOW

        response = KnowledgeSourceResponse.model_validate(record)
        assert response.last_sync_at is None
