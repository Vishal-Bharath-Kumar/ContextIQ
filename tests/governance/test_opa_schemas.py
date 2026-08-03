"""Tests for OPA authorization schemas: ChunkAuthzInput, PolicyDecision,
AuthzFilterResult, and BundleInfo.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.governance.opa.schemas import (
    AuthzFilterResult,
    BundleInfo,
    ChunkAuthzInput,
    PolicyDecision,
)

# ---------------------------------------------------------------------------
# ChunkAuthzInput
# ---------------------------------------------------------------------------


class TestChunkAuthzInput:
    def test_default_classification_label_is_internal(self) -> None:
        obj = ChunkAuthzInput(
            user_roles=["developer"],
            tenant_id="tenant-1",
            source_id="src-abc",
            chunk_id="chunk-1",
        )
        assert obj.classification_label == "internal"

    def test_explicit_classification_label(self) -> None:
        obj = ChunkAuthzInput(
            user_roles=["admin"],
            tenant_id="tenant-1",
            source_id="src-abc",
            chunk_id="chunk-2",
            classification_label="restricted",
        )
        assert obj.classification_label == "restricted"

    def test_default_document_id_is_empty_string(self) -> None:
        obj = ChunkAuthzInput(
            user_roles=[],
            tenant_id="tenant-1",
            source_id="src-abc",
            chunk_id="chunk-3",
        )
        assert obj.document_id == ""

    def test_is_frozen(self) -> None:
        obj = ChunkAuthzInput(
            user_roles=["developer"],
            tenant_id="tenant-1",
            source_id="src-abc",
            chunk_id="chunk-4",
        )
        with pytest.raises((TypeError, ValidationError)):
            obj.classification_label = "public"  # type: ignore[misc]

    def test_tenant_id_min_length(self) -> None:
        with pytest.raises(ValidationError):
            ChunkAuthzInput(
                user_roles=[],
                tenant_id="",
                source_id="src-abc",
                chunk_id="chunk-5",
            )

    def test_tenant_id_max_length(self) -> None:
        with pytest.raises(ValidationError):
            ChunkAuthzInput(
                user_roles=[],
                tenant_id="x" * 129,
                source_id="src-abc",
                chunk_id="chunk-6",
            )

    def test_empty_user_roles_allowed(self) -> None:
        obj = ChunkAuthzInput(
            user_roles=[],
            tenant_id="tenant-1",
            source_id="src-abc",
            chunk_id="chunk-7",
        )
        assert obj.user_roles == []


# ---------------------------------------------------------------------------
# PolicyDecision
# ---------------------------------------------------------------------------


class TestPolicyDecision:
    def test_is_denied_when_allow_false(self) -> None:
        decision = PolicyDecision(
            chunk_id="chunk-1",
            allow=False,
            rationale="No matching role",
            eval_ms=1.5,
        )
        assert decision.is_denied is True

    def test_is_denied_false_when_allow_true(self) -> None:
        decision = PolicyDecision(
            chunk_id="chunk-2",
            allow=True,
            eval_ms=0.8,
        )
        assert decision.is_denied is False

    def test_default_rationale_empty(self) -> None:
        decision = PolicyDecision(chunk_id="chunk-3", allow=True, eval_ms=0.5)
        assert decision.rationale == ""

    def test_eval_ms_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PolicyDecision(chunk_id="chunk-4", allow=True, eval_ms=-0.1)

    def test_eval_ms_zero_is_valid(self) -> None:
        decision = PolicyDecision(chunk_id="chunk-5", allow=True, eval_ms=0.0)
        assert decision.eval_ms == 0.0

    def test_is_frozen(self) -> None:
        decision = PolicyDecision(chunk_id="chunk-6", allow=True, eval_ms=1.0)
        with pytest.raises((TypeError, ValidationError)):
            decision.allow = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AuthzFilterResult
# ---------------------------------------------------------------------------


class TestAuthzFilterResult:
    def _make_result(
        self,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> AuthzFilterResult:
        allowed = allowed if allowed is not None else ["c1", "c2"]
        denied = denied if denied is not None else ["c3"]
        decisions = [
            PolicyDecision(chunk_id=c, allow=True, eval_ms=1.0) for c in allowed
        ] + [PolicyDecision(chunk_id=c, allow=False, eval_ms=1.0) for c in denied]
        return AuthzFilterResult(
            decisions=decisions,
            allowed_chunk_ids=allowed,
            denied_chunk_ids=denied,
            total_eval_ms=3.0,
        )

    def test_denial_count_equals_len_denied_chunk_ids(self) -> None:
        result = self._make_result(denied=["c3", "c4"])
        assert result.denial_count == 2
        assert result.denial_count == len(result.denied_chunk_ids)

    def test_denial_count_zero_when_none_denied(self) -> None:
        result = self._make_result(denied=[])
        assert result.denial_count == 0

    def test_default_bundle_version_is_unknown(self) -> None:
        result = self._make_result()
        assert result.bundle_version == "unknown"

    def test_explicit_bundle_version(self) -> None:
        decisions = [PolicyDecision(chunk_id="c1", allow=True, eval_ms=1.0)]
        result = AuthzFilterResult(
            decisions=decisions,
            allowed_chunk_ids=["c1"],
            denied_chunk_ids=[],
            total_eval_ms=1.0,
            bundle_version="v1.2.3",
        )
        assert result.bundle_version == "v1.2.3"

    def test_is_frozen(self) -> None:
        result = self._make_result()
        with pytest.raises((TypeError, ValidationError)):
            result.bundle_version = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BundleInfo
# ---------------------------------------------------------------------------


class TestBundleInfo:
    def test_valid_bundle_info(self) -> None:
        now = datetime.now(tz=UTC)
        info = BundleInfo(version="v1.0.0", loaded_at=now, source_url="https://opa/bundles/latest")
        assert info.version == "v1.0.0"
        assert info.loaded_at == now
        assert info.source_url == "https://opa/bundles/latest"

    def test_is_frozen(self) -> None:
        now = datetime.now(tz=UTC)
        info = BundleInfo(version="v1.0.0", loaded_at=now, source_url="s3://bucket/bundle.tar.gz")
        with pytest.raises((TypeError, ValidationError)):
            info.version = "v2.0.0"  # type: ignore[misc]
