"""
Unit tests for SQLAlchemy ORM models.
Asserts each model can be instantiated with all required fields (no DB connection needed).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.data.models.connector_config import ConnectorConfig, ConnectorType
from src.data.models.knowledge_source import KnowledgeSource
from src.data.models.knowledge_chunk import KnowledgeChunk
from src.data.models.model_registry import ModelRegistry, ModelStatus
from src.data.models.policy import Policy, PolicyType
from src.data.models.audit_log import AuditLog
from src.data.models.execution_trace_index import ExecutionTraceIndex
from src.data.models.sync_job import SyncJob, SyncStatus


NOW = datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc)
CONNECTOR_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()


class TestConnectorConfig:
    def test_instantiation(self) -> None:
        obj = ConnectorConfig(
            name="test-confluence",
            connector_type=ConnectorType.CONFLUENCE,
            vault_path="secret/contextiq/connectors/confluence",
            created_by="admin",
        )
        assert obj.name == "test-confluence"
        assert obj.connector_type == ConnectorType.CONFLUENCE
        assert obj.enabled is True  # default


class TestKnowledgeSource:
    def test_instantiation(self) -> None:
        obj = KnowledgeSource(
            connector_id=CONNECTOR_ID,
            source_uri="https://confluence.example.com/wiki/page/123",
        )
        assert obj.source_uri == "https://confluence.example.com/wiki/page/123"
        assert obj.title is None

    def test_optional_fields_nullable(self) -> None:
        obj = KnowledgeSource(
            connector_id=CONNECTOR_ID,
            source_uri="https://example.com",
            title="My Page",
            content_hash="abc" * 21 + "d",  # 64 chars
            last_indexed_at=NOW,
        )
        assert obj.content_hash is not None
        assert obj.last_indexed_at == NOW


class TestKnowledgeChunk:
    def test_instantiation(self) -> None:
        obj = KnowledgeChunk(
            source_id=SOURCE_ID,
            chunk_index=0,
            content="First chunk of document content.",
        )
        assert obj.chunk_index == 0
        assert obj.token_count is None
        assert obj.embedding_id is None


class TestModelRegistry:
    def test_instantiation(self) -> None:
        obj = ModelRegistry(
            model_id="gpt-4o",
            provider="openai",
            display_name="GPT-4o",
            context_window=128_000,
        )
        assert obj.model_id == "gpt-4o"
        assert obj.status == ModelStatus.ACTIVE  # default
        assert obj.cost_per_input_token is None


class TestPolicy:
    def test_instantiation(self) -> None:
        obj = Policy(
            name="default-routing",
            policy_type=PolicyType.ROUTING,
            rules={"weights": {"gpt-4o": 0.7, "claude-3-5-sonnet": 0.3}},
            created_by="admin",
        )
        assert obj.enabled is True
        assert obj.priority == 100

    def test_all_policy_types(self) -> None:
        for pt in PolicyType:
            obj = Policy(name=f"policy-{pt.value}", policy_type=pt, rules={}, created_by="x")
            assert obj.policy_type == pt


class TestAuditLog:
    def test_instantiation(self) -> None:
        obj = AuditLog(
            event_type="connector.created",
            resource_type="connector_config",
        )
        assert obj.user_id is None
        assert obj.resource_id is None
        assert obj.ip_address is None

    def test_with_all_fields(self) -> None:
        obj = AuditLog(
            event_type="policy.updated",
            user_id="user-abc",
            resource_type="policy",
            resource_id="pol-123",
            details={"field": "enabled", "old": False, "new": True},
            ip_address="10.0.0.1",
            user_agent="Mozilla/5.0",
        )
        assert obj.details["field"] == "enabled"


class TestExecutionTraceIndex:
    def test_instantiation(self) -> None:
        obj = ExecutionTraceIndex(
            trace_id="0af7651916cd43dd8448eb211c80319c",
            started_at=NOW,
        )
        assert obj.finished_at is None
        assert obj.error is None

    def test_full_fields(self) -> None:
        obj = ExecutionTraceIndex(
            trace_id="abcdef1234567890abcdef1234567890",
            request_id="req-001",
            user_id="user-xyz",
            model_id="claude-3-5-sonnet",
            input_tokens=512,
            output_tokens=1024,
            latency_ms=340,
            started_at=NOW,
            finished_at=NOW,
        )
        assert obj.latency_ms == 340


class TestSyncJob:
    def test_instantiation(self) -> None:
        obj = SyncJob(
            connector_id=CONNECTOR_ID,
            triggered_by="schedule",
        )
        assert obj.status == SyncStatus.PENDING  # default
        assert obj.items_synced == 0
        assert obj.items_failed == 0
        assert obj.error_log is None

    def test_all_sync_statuses(self) -> None:
        for st in SyncStatus:
            obj = SyncJob(connector_id=CONNECTOR_ID, triggered_by="manual", status=st)
            assert obj.status == st
