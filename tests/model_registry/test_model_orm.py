"""Unit tests for ModelRecord ORM — TASK-US018-02.

All tests run without a live database connection.  ORM tests assert
Python-side object construction, column definitions, and server-default
configuration.  DB-level constraints (UNIQUE, CHECK) and index existence
are verified by the Alembic migration test suite.

Acceptance criteria exercised here
-----------------------------------
- ModelRecord can be instantiated with all six registration fields
- ``__tablename__`` is ``"model_registry"``
- ``model_id`` column has ``unique=True``
- ``capabilities`` column stores a list (JSONB); Python-side default is ``list``
- ``latency_tier`` accepts only values matching ``latency_tier_enum``
- ``is_active`` has a ``server_default`` of ``true``; Python-side value may be
  omitted (None before DB flush)
- All expected columns are present on the mapped class
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from src.model_registry.models.model import ModelRecord
from src.model_registry.schemas.model_definition import LatencyTier, ModelCapability

NOW = datetime(2026, 7, 18, 0, 0, 0, tzinfo=UTC)
MODEL_UUID = uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _column(name: str) -> sa.Column:
    """Return the SQLAlchemy Column object for *name* from ModelRecord."""
    mapper = sa_inspect(ModelRecord)
    return mapper.columns[name]


# ---------------------------------------------------------------------------
# Table metadata
# ---------------------------------------------------------------------------

class TestTableMetadata:
    def test_tablename(self) -> None:
        assert ModelRecord.__tablename__ == "model_registry"

    def test_all_expected_columns_present(self) -> None:
        mapper = sa_inspect(ModelRecord)
        col_names = {col.key for col in mapper.columns}
        required = {
            "id",
            "model_id",
            "provider",
            "context_window",
            "cost_per_1k_tokens",
            "latency_tier",
            "capabilities",
            "is_active",
            "created_at",
            "updated_at",
        }
        assert required <= col_names


# ---------------------------------------------------------------------------
# Column constraints
# ---------------------------------------------------------------------------

class TestColumnConstraints:
    def test_model_id_is_unique(self) -> None:
        col = _column("model_id")
        assert col.unique is True

    def test_model_id_not_nullable(self) -> None:
        assert _column("model_id").nullable is False

    def test_provider_not_nullable(self) -> None:
        assert _column("provider").nullable is False

    def test_context_window_not_nullable(self) -> None:
        assert _column("context_window").nullable is False

    def test_cost_per_1k_tokens_not_nullable(self) -> None:
        assert _column("cost_per_1k_tokens").nullable is False

    def test_latency_tier_not_nullable(self) -> None:
        assert _column("latency_tier").nullable is False

    def test_capabilities_not_nullable(self) -> None:
        assert _column("capabilities").nullable is False

    def test_is_active_not_nullable(self) -> None:
        assert _column("is_active").nullable is False

    def test_is_active_server_default_is_true(self) -> None:
        col = _column("is_active")
        assert col.server_default is not None
        assert "true" in str(col.server_default.arg).lower()

    def test_created_at_has_server_default(self) -> None:
        col = _column("created_at")
        assert col.server_default is not None

    def test_updated_at_has_server_default(self) -> None:
        col = _column("updated_at")
        assert col.server_default is not None

    def test_id_is_primary_key(self) -> None:
        col = _column("id")
        assert col.primary_key is True


# ---------------------------------------------------------------------------
# ORM instantiation — no DB required
# ---------------------------------------------------------------------------

class TestModelRecordInstantiation:
    def test_minimal_required_fields(self) -> None:
        record = ModelRecord(
            model_id="gpt-4o-mini",
            provider="openai",
            context_window=128_000,
            cost_per_1k_tokens=0.15,
            latency_tier=LatencyTier.FAST,
            capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALL],
        )
        assert record.model_id == "gpt-4o-mini"
        assert record.provider == "openai"
        assert record.context_window == 128_000
        assert record.cost_per_1k_tokens == 0.15
        assert record.latency_tier == LatencyTier.FAST
        assert ModelCapability.CHAT in record.capabilities

    def test_explicit_id_accepted(self) -> None:
        record = ModelRecord(
            id=MODEL_UUID,
            model_id="anthropic/claude-3-haiku",
            provider="anthropic",
            context_window=200_000,
            cost_per_1k_tokens=0.25,
            latency_tier=LatencyTier.MEDIUM,
            capabilities=[ModelCapability.VISION],
        )
        assert record.id == MODEL_UUID

    def test_is_active_none_before_db_flush(self) -> None:
        """is_active has a server_default; Python-side it may be None until flushed."""
        record = ModelRecord(
            model_id="o1",
            provider="openai",
            context_window=128_000,
            cost_per_1k_tokens=15.0,
            latency_tier=LatencyTier.SLOW,
            capabilities=[ModelCapability.CODE],
        )
        # server_default applies at INSERT time; value is None before flush
        assert record.is_active is None

    def test_capabilities_default_is_none_before_db_flush(self) -> None:
        """Column default=list is an insert-time default; Python-side value is
        None before the row is flushed to the database."""
        record = ModelRecord(
            model_id="text-embedding-3-small",
            provider="openai",
            context_window=8_191,
            cost_per_1k_tokens=0.02,
            latency_tier=LatencyTier.FAST,
        )
        # server/insert defaults are applied at INSERT time, not object construction
        assert record.capabilities is None

    def test_capabilities_explicit_list_accepted(self) -> None:
        """Explicitly passing a list is stored as-is before DB flush."""
        record = ModelRecord(
            model_id="text-embedding-3-small",
            provider="openai",
            context_window=8_191,
            cost_per_1k_tokens=0.02,
            latency_tier=LatencyTier.FAST,
            capabilities=[],
        )
        assert isinstance(record.capabilities, list)

    def test_all_latency_tiers_accepted(self) -> None:
        for tier in LatencyTier:
            record = ModelRecord(
                model_id=f"model-{tier.value}",
                provider="test",
                context_window=4_096,
                cost_per_1k_tokens=0.0,
                latency_tier=tier,
                capabilities=[ModelCapability.COMPLETION],
            )
            assert record.latency_tier == tier

    def test_zero_cost_accepted(self) -> None:
        record = ModelRecord(
            model_id="free-model",
            provider="local",
            context_window=4_096,
            cost_per_1k_tokens=0.0,
            latency_tier=LatencyTier.FAST,
            capabilities=[ModelCapability.CHAT],
        )
        assert record.cost_per_1k_tokens == 0.0


# ---------------------------------------------------------------------------
# JSONB capabilities round-trip (Python-side)
# ---------------------------------------------------------------------------

class TestCapabilitiesJsonb:
    def test_list_of_capability_strings_stored(self) -> None:
        caps = [ModelCapability.CHAT, ModelCapability.CODE, ModelCapability.VISION]
        record = ModelRecord(
            model_id="gpt-4o",
            provider="openai",
            context_window=128_000,
            cost_per_1k_tokens=5.0,
            latency_tier=LatencyTier.MEDIUM,
            capabilities=caps,
        )
        assert record.capabilities == caps

    def test_single_capability(self) -> None:
        record = ModelRecord(
            model_id="embed-model",
            provider="openai",
            context_window=8_191,
            cost_per_1k_tokens=0.02,
            latency_tier=LatencyTier.FAST,
            capabilities=[ModelCapability.EMBEDDING],
        )
        assert record.capabilities == [ModelCapability.EMBEDDING]

    def test_all_capabilities_accepted(self) -> None:
        record = ModelRecord(
            model_id="all-caps-model",
            provider="test",
            context_window=32_000,
            cost_per_1k_tokens=1.0,
            latency_tier=LatencyTier.MEDIUM,
            capabilities=list(ModelCapability),
        )
        assert len(record.capabilities) == len(ModelCapability)
