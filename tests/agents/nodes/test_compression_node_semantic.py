"""Tests for TASK-US016-05 — compression_node two-stage extension.

Coverage:
- compression_node runs RuleBasedCompressor (stage 1) then SemanticDeduplicator (stage 2).
- removed_chunks combines records from both compression stages.
- consolidated_sources is None when no semantic merges occurred.
- consolidated_sources maps retained_chunk_id → absorbed source_ids when merges occurred.
- Combined pipeline achieves >= 15% token reduction on a redundant multi-source fixture.
- _compressor and _semantic_dedup are module-level singletons (not re-instantiated per call).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import src.agents.nodes.compression as compression_module
from src.agents.nodes.compression import compression_node
from src.agents.state import AgentState, ExecutionStatus
from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk
from src.compression.semantic.semantic_deduplicator import SemanticDeduplicator
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EMBED_DIM = 384
_NOW = datetime.now(UTC)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(
    chunk_id: str,
    content: str,
    source_id: str = "github",
    score: float = 0.8,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        content=content,
        score=score,
        metadata=ChunkMetadata(
            file_path=f"src/{chunk_id}.py",
            timestamp=_NOW,
            author="test-author",
        ),
        search_mode="rrf",
    )


def _make_state(**overrides: object) -> AgentState:
    base: AgentState = {
        "request_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "user-1",
        "username": "tester",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": "How does the deployment pipeline work?",
        "timestamp": "2026-07-17T00:00:00Z",
        "status": ExecutionStatus.RUNNING,
        "current_node": "governance_agent",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
        "compressed_context": None,
        "removed_chunks": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
    }
    return {**base, **overrides}  # type: ignore[return-value]


def _removed_chunk(chunk_id: str, reason: RemovalReason, source_id: str = "github") -> RemovedChunk:
    return RemovedChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        reason=reason,
        original_content=f"content of {chunk_id}",
    )


# ---------------------------------------------------------------------------
# Multi-source redundant fixture for token-reduction integration test
# ---------------------------------------------------------------------------

# Boilerplate phrase matched by the SPDX rule (BoilerplateDetector picks this up).
_BOILERPLATE_PREFIX = "SPDX-License-Identifier: MIT\n"

# Each "near-duplicate group" has 3 chunks from different sources but near-identical
# text content.  After the rule-based stage removes the 10 boilerplate chunks, the
# mock embedder returns near-identical vectors for each group so the semantic stage
# can collapse each group to 1 representative.
_NEAR_DUP_SOURCES = ["confluence", "github", "jira"]


def _make_redundant_multi_source_chunks(n: int) -> list[RetrievedChunk]:
    """Return *n* chunks arranged as: 25 unique | 15 near-dup (5 groups×3) | 10 boilerplate.

    Design:
    - 20 % boilerplate  (10 chunks): contain SPDX header → removed by rule-based stage.
    - 30 % near-dup     (15 chunks): slightly different content, but mock embedder returns
                                     near-identical vectors → 10 removed by semantic stage.
    - 50 % unique       (25 chunks): distinct content → all retained.

    Expected combined reduction: (10 + 10) / 50 = 40 % ≥ 15 % AC.
    """
    n_unique = n // 2          # 25
    n_neardup = (n * 3) // 10  # 15
    n_boilerplate = n - n_unique - n_neardup  # 10

    chunks: list[RetrievedChunk] = []

    # ── 25 unique chunks ──────────────────────────────────────────────
    for i in range(n_unique):
        chunks.append(
            _chunk(
                chunk_id=f"unique_{i:03d}",
                content=(
                    f"Unique deployment context entry {i}. "
                    "This document describes the CI/CD pipeline configuration and "
                    "the automated testing strategy used for production deployments. "
                    "Each service follows a blue-green deployment strategy with "
                    "automatic rollback on health check failure."
                ),
                source_id="github",
                score=round(0.9 - i * 0.001, 4),
            )
        )

    # ── 15 near-dup chunks (5 groups × 3) ────────────────────────────
    groups = n_neardup // 3  # 5 groups
    for g in range(groups):
        for j, src in enumerate(_NEAR_DUP_SOURCES):
            chunks.append(
                _chunk(
                    chunk_id=f"neardup_{g:02d}_{j}",
                    content=(
                        f"Kubernetes deployment manifest version {g}.{j}. "
                        "The replica count is set to three with a rolling update "
                        "strategy and a maximum surge of one pod. "
                        "Resource limits are defined per container."
                    ),
                    source_id=src,
                    score=round(0.85 - g * 0.01, 4),
                )
            )

    # ── 10 boilerplate chunks ─────────────────────────────────────────
    for i in range(n_boilerplate):
        chunks.append(
            _chunk(
                chunk_id=f"boiler_{i:03d}",
                content=(
                    f"{_BOILERPLATE_PREFIX}"
                    f"Auto-generated file {i}. DO NOT EDIT.\n"
                    "This file contains generated stubs and should not be modified."
                ),
                source_id="github",
                score=0.5,
            )
        )

    return chunks


def _make_near_dup_embeddings(n_unique: int, n_neardup: int, n_groups: int) -> np.ndarray:
    """Return embedding matrix where near-dup group members share near-identical vectors.

    Shape: (n_unique + n_neardup, EMBED_DIM).
    Cosine similarity within each group > 0.99 (well above the 0.92 threshold).
    """
    rng = np.random.default_rng(42)
    per_group = n_neardup // n_groups  # 3

    # Unique chunks: independent random unit vectors
    unique_raw = rng.standard_normal((n_unique, _EMBED_DIM)).astype(np.float32)
    norms = np.linalg.norm(unique_raw, axis=1, keepdims=True)
    unique_vecs = unique_raw / norms

    # Near-dup groups: 5 base vectors, each tiled 3× with tiny noise
    base_raw = rng.standard_normal((n_groups, _EMBED_DIM)).astype(np.float32)
    base_norms = np.linalg.norm(base_raw, axis=1, keepdims=True)
    base_vecs = base_raw / base_norms
    tiled = np.repeat(base_vecs, per_group, axis=0)
    tiled += rng.standard_normal(tiled.shape).astype(np.float32) * 5e-4  # tiny noise

    return np.vstack([unique_vecs, tiled[:n_neardup]])


# ---------------------------------------------------------------------------
# TestCompressionNodeTwoStages
# ---------------------------------------------------------------------------


class TestCompressionNodeTwoStages:
    """Verify the two-stage compression pipeline order and data flow."""

    @pytest.mark.asyncio
    async def test_stage1_runs_before_stage2(self) -> None:
        """SemanticDeduplicator receives the rule-based output, not the raw input."""
        raw = [
            _chunk("s1a", "keep this content A"),
            _chunk("s1b", "exact duplicate of A"),
        ]
        after_rules = [raw[0]]  # rule-based keeps only the first chunk
        state = _make_state(ranked_context=raw)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_rule, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_sem, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_rule.compress.return_value = (after_rules, [_removed_chunk("s1b", RemovalReason.EXACT_DUPLICATE)])
            mock_sem.deduplicate.side_effect = lambda c: (c, [], {})
            await compression_node(state)

        # Stage 2 must receive the output of stage 1, not the original raw list
        call_args = mock_sem.deduplicate.call_args
        assert call_args is not None
        passed_chunks = call_args.args[0] if call_args.args else call_args.kwargs.get("chunks")
        assert passed_chunks == after_rules

    @pytest.mark.asyncio
    async def test_removed_chunks_combines_both_stages(self) -> None:
        """removed_chunks in state = rule_removed + semantic_removed."""
        chunks = [
            _chunk("r1", "keep A"),
            _chunk("r2", "boilerplate footer"),
            _chunk("r3", "near-dup of A", source_id="jira"),
        ]
        after_rules = [chunks[0], chunks[2]]
        rule_removed = [_removed_chunk("r2", RemovalReason.BOILERPLATE)]
        sem_removed = [
            RemovedChunk(
                chunk_id="r3",
                source_id="jira",
                reason=RemovalReason.SEMANTIC_NEAR_DUP,
                duplicate_of="r1",
                original_content="near-dup of A",
            )
        ]
        after_semantic = [chunks[0]]
        state = _make_state(ranked_context=chunks)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_rule, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_sem, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_rule.compress.return_value = (after_rules, rule_removed)
            mock_sem.deduplicate.return_value = (after_semantic, sem_removed, {"r1": ["jira"]})
            result = await compression_node(state)

        assert result["removed_chunks"] == rule_removed + sem_removed
        assert len(result["removed_chunks"]) == 2
        assert result["removed_chunks"][0].reason == RemovalReason.BOILERPLATE
        assert result["removed_chunks"][1].reason == RemovalReason.SEMANTIC_NEAR_DUP

    @pytest.mark.asyncio
    async def test_consolidated_sources_none_when_no_semantic_merges(self) -> None:
        """consolidated_sources is None when SemanticDeduplicator returns empty consolidated dict."""
        chunks = [_chunk("n1", "unique A"), _chunk("n2", "unique B")]
        state = _make_state(ranked_context=chunks)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_rule, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_sem, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_rule.compress.return_value = (chunks, [])
            mock_sem.deduplicate.return_value = (chunks, [], {})  # no merges → empty dict
            result = await compression_node(state)

        assert result["consolidated_sources"] is None

    @pytest.mark.asyncio
    async def test_consolidated_sources_populated_when_merges_occur(self) -> None:
        """consolidated_sources maps retained chunk_id → absorbed source_ids."""
        chunks = [
            _chunk("m1", "context A", source_id="github"),
            _chunk("m2", "context A near-dup", source_id="confluence"),
        ]
        after_semantic = [chunks[0]]
        consolidated = {"m1": ["confluence"]}
        state = _make_state(ranked_context=chunks)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_rule, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_sem, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_rule.compress.return_value = (chunks, [])
            mock_sem.deduplicate.return_value = (
                after_semantic,
                [_removed_chunk("m2", RemovalReason.SEMANTIC_NEAR_DUP, "confluence")],
                consolidated,
            )
            result = await compression_node(state)

        assert result["consolidated_sources"] == {"m1": ["confluence"]}

    @pytest.mark.asyncio
    async def test_compressed_context_is_stage2_output(self) -> None:
        """compressed_context reflects the result of the semantic stage, not stage 1."""
        chunks = [_chunk("e1", "text A"), _chunk("e2", "text B"), _chunk("e3", "text C")]
        after_rules = [chunks[0], chunks[1]]   # stage 1 removes e3
        after_semantic = [chunks[0]]           # stage 2 removes e2
        state = _make_state(ranked_context=chunks)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_rule, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_sem, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_rule.compress.return_value = (after_rules, [_removed_chunk("e3", RemovalReason.BOILERPLATE)])
            sem_removed = [_removed_chunk("e2", RemovalReason.SEMANTIC_NEAR_DUP)]
            mock_sem.deduplicate.return_value = (after_semantic, sem_removed, {})
            result = await compression_node(state)

        assert result["compressed_context"] == after_semantic
        assert result["ranked_context"] == after_semantic


# ---------------------------------------------------------------------------
# TestCompressionNodeSingletons
# ---------------------------------------------------------------------------


class TestCompressionNodeSingletons:
    """Verify singleton semantics — neither compressor is re-instantiated per call."""

    def test_compressor_singleton_is_module_level(self) -> None:
        """_compressor is a RuleBasedCompressor instance set at module load, not per call."""
        from src.compression.rule_based_compressor import RuleBasedCompressor

        assert isinstance(compression_module._compressor, RuleBasedCompressor)

    def test_semantic_dedup_module_attribute_exists(self) -> None:
        """_semantic_dedup module attribute exists (None until first call, then singleton)."""
        assert hasattr(compression_module, "_semantic_dedup")

    @pytest.mark.asyncio
    async def test_semantic_dedup_not_reinstantiated_across_calls(self) -> None:
        """After first call, _semantic_dedup singleton is reused on subsequent calls."""
        mock_dedup = MagicMock(spec=SemanticDeduplicator)
        mock_dedup.deduplicate.side_effect = lambda c: (c, [], {})
        chunks = [_chunk("sc1", "content")]
        state = _make_state(ranked_context=chunks)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_rule, patch(
            "src.agents.nodes.compression._semantic_dedup", mock_dedup
        ), patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_rule.compress.return_value = (chunks, [])
            await compression_node(state)
            await compression_node(state)

        # The same mock instance served both calls — deduplicate called twice
        assert mock_dedup.deduplicate.call_count == 2


# ---------------------------------------------------------------------------
# Integration test: >= 15% combined token reduction (AC-5)
# ---------------------------------------------------------------------------


def test_combined_compression_reduces_tokens_by_15_percent() -> None:
    """Mock embedder returns near-identical vectors for near-dup groups.

    Fixture structure (50 chunks):
    - 25 unique chunks  (kept)
    - 15 near-dup chunks, 5 groups × 3 (10 removed by semantic stage)
    - 10 boilerplate chunks (removed by rule-based stage via SPDX pattern)

    Expected combined reduction: (10 + 10) / 50 = 40 % >= 15 % AC.
    """
    from src.retrieval.ranking.filters import count_tokens

    n = 50
    n_unique = n // 2       # 25
    n_neardup = (n * 3) // 10  # 15
    n_groups = n_neardup // 3  # 5

    chunks = _make_redundant_multi_source_chunks(n)
    assert len(chunks) == n

    # After stage 1, the 10 boilerplate chunks are removed; 40 remain.
    # The embedder receives texts for those 40 chunks: 25 unique + 15 near-dup.
    embeddings_stage2 = _make_near_dup_embeddings(n_unique, n_neardup, n_groups)

    mock_embedder = MagicMock()
    mock_embedder.embed_batch.return_value = embeddings_stage2

    semantic_dedup_with_mock = SemanticDeduplicator(embedder=mock_embedder)

    async def _run() -> dict:
        state = _make_state(ranked_context=chunks)
        with patch(
            "src.agents.nodes.compression._semantic_dedup", semantic_dedup_with_mock
        ), patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            return await compression_node(state)

    result = asyncio.run(_run())

    original_tokens = sum(count_tokens(c.content) for c in chunks)
    compressed_tokens = sum(count_tokens(c.content) for c in result["compressed_context"])
    reduction = (original_tokens - compressed_tokens) / original_tokens

    assert reduction >= 0.15, (
        f"Combined two-stage reduction {reduction:.1%} < 15% AC requirement. "
        f"original={original_tokens} compressed={compressed_tokens} "
        f"removed={len(result['removed_chunks'])}"
    )
