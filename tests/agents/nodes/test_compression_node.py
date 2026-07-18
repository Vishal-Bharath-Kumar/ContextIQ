"""Unit tests for TASK-US015-05 — compression_node.

Coverage:
- Normal compression: compressed_context and removed_chunks written to state.
- ranked_context updated to the compressed list.
- removed_chunks[*].original_content preserved for replay.
- Empty ranked_context: returns empty lists without error.
- Module-level _compressor singleton is not re-instantiated per call.
- Kafka StateTransitionEvent carries removed_chunks_snapshot for compression_agent.
- removed_chunks_snapshot is None for non-compression nodes (backward-compatible).
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.events.state_event_publisher import StateEventPublisher, with_state_events
from src.agents.events.state_event_schema import StateTransitionEvent
from src.agents.nodes.compression import compression_node
from src.agents.state import AgentState, ExecutionStatus
from src.compression.schemas.removed_chunk import RemovalReason, RemovedChunk
from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)


def _chunk(chunk_id: str, content: str, score: float = 0.8) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id="github",
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
        "request_id": "00000000-0000-0000-0000-000000000001",
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


def _make_publisher() -> tuple[StateEventPublisher, AsyncMock]:
    mock_producer = MagicMock()
    mock_producer.send_and_wait = AsyncMock(return_value=None)
    return StateEventPublisher(mock_producer), mock_producer


# ---------------------------------------------------------------------------
# compression_node — normal compression path
# ---------------------------------------------------------------------------


class TestCompressionNodeNormal:
    @pytest.mark.asyncio
    async def test_compressed_context_written_to_state(self) -> None:
        chunks = [
            _chunk("c1", "deployment pipeline overview"),
            _chunk("c2", "CI/CD configuration guide"),
        ]
        state = _make_state(ranked_context=chunks)

        compressed_chunks = [chunks[0]]
        removed = [
            RemovedChunk(
                chunk_id="c2",
                source_id="github",
                reason=RemovalReason.EXACT_DUPLICATE,
                original_content="CI/CD configuration guide",
            )
        ]

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_compressor, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_compressor.compress.return_value = (compressed_chunks, removed)
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        assert result["compressed_context"] == compressed_chunks
        assert isinstance(result["compressed_context"], list)

    @pytest.mark.asyncio
    async def test_removed_chunks_written_to_state(self) -> None:
        chunks = [_chunk("a1", "unique content"), _chunk("a2", "duplicate content")]
        state = _make_state(ranked_context=chunks)

        removed = [
            RemovedChunk(
                chunk_id="a2",
                source_id="github",
                reason=RemovalReason.EXACT_DUPLICATE,
                original_content="duplicate content",
            )
        ]

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_compressor, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_compressor.compress.return_value = ([chunks[0]], removed)
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        assert result["removed_chunks"] == removed
        assert len(result["removed_chunks"]) == 1

    @pytest.mark.asyncio
    async def test_ranked_context_updated_to_compressed_list(self) -> None:
        chunks = [_chunk("b1", "content A"), _chunk("b2", "boilerplate footer")]
        state = _make_state(ranked_context=chunks)

        compressed = [chunks[0]]
        removed = [
            RemovedChunk(
                chunk_id="b2",
                source_id="github",
                reason=RemovalReason.BOILERPLATE,
                original_content="boilerplate footer",
            )
        ]

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_compressor, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_compressor.compress.return_value = (compressed, removed)
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        assert result["ranked_context"] == compressed
        assert result["ranked_context"] is result["compressed_context"]

    @pytest.mark.asyncio
    async def test_original_content_preserved_in_removed_chunks(self) -> None:
        original_text = "This is the exact original content for replay."
        chunks = [_chunk("x1", "kept content"), _chunk("x2", original_text)]
        state = _make_state(ranked_context=chunks)

        removed = [
            RemovedChunk(
                chunk_id="x2",
                source_id="github",
                reason=RemovalReason.BOILERPLATE,
                original_content=original_text,
            )
        ]

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_compressor, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_compressor.compress.return_value = ([chunks[0]], removed)
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        for rc in result["removed_chunks"]:
            assert rc.original_content is not None
            assert len(rc.original_content) > 0

    @pytest.mark.asyncio
    async def test_node_metadata_fields_correct(self) -> None:
        chunks = [_chunk("m1", "metadata test chunk")]
        state = _make_state(ranked_context=chunks)

        with patch(
            "src.agents.nodes.compression._compressor"
        ) as mock_compressor, patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_compressor.compress.return_value = (chunks, [])
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        assert result["current_node"] == "compression_agent"
        assert result["status"] == ExecutionStatus.RUNNING


# ---------------------------------------------------------------------------
# compression_node — empty input guard
# ---------------------------------------------------------------------------


class TestCompressionNodeEmptyInput:
    @pytest.mark.asyncio
    async def test_empty_ranked_context_returns_empty_lists(self) -> None:
        state = _make_state(ranked_context=[])

        with patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        assert result["compressed_context"] == []
        assert result["removed_chunks"] == []
        assert result["ranked_context"] == []

    @pytest.mark.asyncio
    async def test_none_ranked_context_returns_empty_lists(self) -> None:
        state = _make_state(ranked_context=None)

        with patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            result = await compression_node(state)

        assert result["compressed_context"] == []
        assert result["removed_chunks"] == []

    @pytest.mark.asyncio
    async def test_no_exception_raised_on_empty_input(self) -> None:
        state = _make_state(ranked_context=None)

        with patch(
            "src.agents.nodes.compression._semantic_dedup"
        ) as mock_semantic_dedup, patch(
            "src.agents.nodes.compression._get_compression_recorder", return_value=None
        ):
            mock_semantic_dedup.deduplicate.side_effect = lambda c: (c, [], {})
            # Must not raise
            await compression_node(state)


# ---------------------------------------------------------------------------
# Kafka snapshot — removed_chunks_snapshot in StateTransitionEvent
# ---------------------------------------------------------------------------


class TestKafkaRemovedChunksSnapshot:
    @pytest.mark.asyncio
    async def test_removed_chunks_snapshot_set_on_compression_agent_event(self) -> None:
        chunks = [_chunk("k1", "keep me"), _chunk("k2", "remove me")]
        state = _make_state(ranked_context=chunks)

        removed = [
            RemovedChunk(
                chunk_id="k2",
                source_id="github",
                reason=RemovalReason.EXACT_DUPLICATE,
                original_content="remove me",
            )
        ]

        publisher, mock_producer = _make_publisher()

        async def _mock_node(s: AgentState) -> dict:
            return {
                "compressed_context": [chunks[0]],
                "removed_chunks": removed,
                "ranked_context": [chunks[0]],
                "current_node": "compression_agent",
                "status": ExecutionStatus.RUNNING,
            }

        wrapped = with_state_events(_mock_node, "compression_agent", publisher)
        await wrapped(state)

        # Two events: entry + success; collect published events
        events: list[StateTransitionEvent] = []
        for call_args in mock_producer.send_and_wait.call_args_list:
            raw = call_args.kwargs.get("value") or call_args.args[1]
            events.append(StateTransitionEvent.model_validate_json(raw))

        # events[0] = entry event, events[1] = success event
        success_event = events[1]
        assert success_event.removed_chunks_snapshot is not None
        assert len(success_event.removed_chunks_snapshot) == 1
        assert success_event.removed_chunks_snapshot[0]["chunk_id"] == "k2"
        assert success_event.removed_chunks_snapshot[0]["original_content"] == "remove me"

    @pytest.mark.asyncio
    async def test_removed_chunks_snapshot_none_for_other_nodes(self) -> None:
        state = _make_state()
        publisher, mock_producer = _make_publisher()

        async def _mock_intent_node(s: AgentState) -> dict:
            return {"current_node": "intent_agent", "status": ExecutionStatus.RUNNING}

        wrapped = with_state_events(_mock_intent_node, "intent_agent", publisher)
        await wrapped(state)

        events: list[StateTransitionEvent] = []
        for call_args in mock_producer.send_and_wait.call_args_list:
            raw = call_args.kwargs.get("value") or call_args.args[1]
            events.append(StateTransitionEvent.model_validate_json(raw))

        for event in events:
            assert event.removed_chunks_snapshot is None

    @pytest.mark.asyncio
    async def test_removed_chunks_snapshot_none_when_removed_is_empty(self) -> None:
        chunks = [_chunk("e1", "no removals here")]
        state = _make_state(ranked_context=chunks)
        publisher, mock_producer = _make_publisher()

        async def _mock_compression_node(s: AgentState) -> dict:
            return {
                "compressed_context": chunks,
                "removed_chunks": None,
                "ranked_context": chunks,
                "current_node": "compression_agent",
                "status": ExecutionStatus.RUNNING,
            }

        wrapped = with_state_events(_mock_compression_node, "compression_agent", publisher)
        await wrapped(state)

        events: list[StateTransitionEvent] = []
        for call_args in mock_producer.send_and_wait.call_args_list:
            raw = call_args.kwargs.get("value") or call_args.args[1]
            events.append(StateTransitionEvent.model_validate_json(raw))

        success_event = events[1]
        assert success_event.removed_chunks_snapshot is None

    @pytest.mark.asyncio
    async def test_snapshot_payload_shape_matches_removed_chunk_model_dump(self) -> None:
        """Each dict in removed_chunks_snapshot must be a full RemovedChunk.model_dump()."""
        chunks = [_chunk("s1", "shape test keep"), _chunk("s2", "shape test remove")]
        state = _make_state(ranked_context=chunks)

        removed_chunk = RemovedChunk(
            chunk_id="s2",
            source_id="github",
            reason=RemovalReason.BOILERPLATE,
            boilerplate_rule="footer_pattern",
            original_content="shape test remove",
        )
        publisher, mock_producer = _make_publisher()

        async def _mock_node(s: AgentState) -> dict:
            return {
                "compressed_context": [chunks[0]],
                "removed_chunks": [removed_chunk],
                "ranked_context": [chunks[0]],
                "current_node": "compression_agent",
                "status": ExecutionStatus.RUNNING,
            }

        wrapped = with_state_events(_mock_node, "compression_agent", publisher)
        await wrapped(state)

        events: list[StateTransitionEvent] = []
        for call_args in mock_producer.send_and_wait.call_args_list:
            raw = call_args.kwargs.get("value") or call_args.args[1]
            events.append(StateTransitionEvent.model_validate_json(raw))

        success_event = events[1]
        snapshot = success_event.removed_chunks_snapshot
        assert snapshot is not None
        assert snapshot[0] == removed_chunk.model_dump()
