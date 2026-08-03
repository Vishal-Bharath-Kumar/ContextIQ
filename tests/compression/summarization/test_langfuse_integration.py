"""Integration tests for Langfuse callback handler and compression_node Stage 3 (TASK-US017-05)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# make_langfuse_handler tests
# ---------------------------------------------------------------------------


class TestMakeLangfuseHandler:
    """Tests for src.compression.summarization.langfuse_handler.make_langfuse_handler."""

    def test_returns_none_when_langfuse_disabled(self) -> None:
        """AC: SUMMARIZATION_LANGFUSE_ENABLED=false returns None without error."""
        mock_settings = MagicMock()
        mock_settings.langfuse_enabled = False

        with patch(
            "src.compression.summarization.langfuse_handler.get_summarization_settings",
            return_value=mock_settings,
        ):
            import src.compression.summarization.langfuse_handler as _mod

            result = _mod.make_langfuse_handler(
                request_id="req-123",
                user_id="user-abc",
                session_id="req-123",
            )

        assert result is None

    def test_returns_callback_handler_when_enabled(self) -> None:
        """AC: returns a CallbackHandler instance when langfuse_enabled=True."""
        mock_settings = MagicMock()
        mock_settings.langfuse_enabled = True

        mock_langfuse_settings = MagicMock()
        mock_langfuse_settings.public_key = "pk-lf-test"
        mock_langfuse_settings.secret_key = "sk-lf-test"
        mock_langfuse_settings.host = "https://cloud.langfuse.com"

        mock_handler_instance = MagicMock()
        mock_handler_cls = MagicMock(return_value=mock_handler_instance)

        with (
            patch(
                "src.compression.summarization.langfuse_handler.get_summarization_settings",
                return_value=mock_settings,
            ),
            patch(
                "src.compression.summarization.langfuse_handler._RequiredLangfuseCredentials",
            ),
            patch(
                "src.compression.summarization.langfuse_handler.LangfuseProjectSettings",
                return_value=mock_langfuse_settings,
            ),
            patch.dict(
                "sys.modules",
                {"langfuse.callback": MagicMock(CallbackHandler=mock_handler_cls)},
            ),
            patch(
                "src.compression.summarization.langfuse_handler._langfuse_settings",
                None,
            ),
        ):
            # Reset module-level singleton to force lazy init path
            import src.compression.summarization.langfuse_handler as _mod
            _mod._langfuse_settings = None

            result = _mod.make_langfuse_handler(
                request_id="req-xyz",
                user_id="user-42",
                session_id="req-xyz",
            )

        assert result is mock_handler_instance
        mock_handler_cls.assert_called_once_with(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="https://cloud.langfuse.com",
            trace_name="context_summarization",
            metadata={
                "request_id": "req-xyz",
                "user_id": "user-42",
                "session_id": "req-xyz",
            },
            tags=["compression", "summarization"],
        )

    def test_handler_carries_request_metadata(self) -> None:
        """AC: trace metadata contains request_id and user_id."""
        mock_settings = MagicMock()
        mock_settings.langfuse_enabled = True

        mock_langfuse_settings = MagicMock()
        mock_langfuse_settings.public_key = "pk-lf-test"
        mock_langfuse_settings.secret_key = "sk-lf-test"
        mock_langfuse_settings.host = "https://cloud.langfuse.com"

        mock_handler_cls = MagicMock()

        with (
            patch(
                "src.compression.summarization.langfuse_handler.get_summarization_settings",
                return_value=mock_settings,
            ),
            patch(
                "src.compression.summarization.langfuse_handler._RequiredLangfuseCredentials",
            ),
            patch(
                "src.compression.summarization.langfuse_handler.LangfuseProjectSettings",
                return_value=mock_langfuse_settings,
            ),
            patch.dict(
                "sys.modules",
                {"langfuse.callback": MagicMock(CallbackHandler=mock_handler_cls)},
            ),
        ):
            import src.compression.summarization.langfuse_handler as _mod
            _mod._langfuse_settings = None

            _mod.make_langfuse_handler(
                request_id="trace-001",
                user_id="u-999",
                session_id="trace-001",
            )

        _, kwargs = mock_handler_cls.call_args
        assert kwargs["metadata"]["request_id"] == "trace-001"
        assert kwargs["metadata"]["user_id"] == "u-999"
        assert kwargs["metadata"]["session_id"] == "trace-001"

    def test_missing_public_key_raises_validation_error_when_enabled(self) -> None:
        """AC: LANGFUSE_PUBLIC_KEY not set raises ValidationError at startup when enabled=True."""
        with patch.dict(
            "os.environ",
            {
                "SUMMARIZATION_LANGFUSE_ENABLED": "true",
                "LANGFUSE_PUBLIC_KEY": "",
                "LANGFUSE_SECRET_KEY": "",
            },
            clear=False,
        ):
            from src.compression.summarization.langfuse_handler import _RequiredLangfuseCredentials

            with pytest.raises(ValidationError, match="LANGFUSE_PUBLIC_KEY"):
                _RequiredLangfuseCredentials(public_key="", secret_key="", host="https://cloud.langfuse.com")


# ---------------------------------------------------------------------------
# compression_node Stage 3 integration
# ---------------------------------------------------------------------------


class TestCompressionNodeStage3:
    """Tests that compression_node runs all three stages and passes Langfuse callbacks."""

    @pytest.fixture()
    def base_state(self) -> dict:
        from src.agents.state import ExecutionStatus

        return {
            "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "user_id": "user-stage3",
            "username": "tester",
            "roles": [],
            "tool_name": "test_tool",
            "prompt": "test prompt",
            "timestamp": "2026-01-01T00:00:00Z",
            "status": ExecutionStatus.RUNNING,
            "current_node": "retrieval_agent",
            "error": None,
            "ranked_context": [],
            "intent_type": None,
            "intent_confidence": None,
            "intent_source_list": None,
            "execution_plan": None,
            "requires_clarification": None,
            "clarification_question": None,
            "clarification_round": 0,
            "raw_context": None,
            "degraded_sources": None,
            "compressed_context": None,
            "removed_chunks": None,
            "tokens_before_compression": 0,
            "tokens_after_compression": 0,
            "governance_decisions": None,
            "redacted_chunks": None,
            "selected_model": None,
            "model_routing_score": None,
            "final_response": None,
            "jwt_claims": {"sub": "user-stage3"},
        }

    @pytest.mark.asyncio
    async def test_stage3_summarizer_called_with_langfuse_handler(
        self, base_state: dict
    ) -> None:
        """AC: ChunkSummarizer is instantiated per call with the Langfuse handler in callbacks."""
        mock_handler = MagicMock()
        mock_summarizer = MagicMock()
        mock_summarizer.summarize = AsyncMock(return_value=[])

        with (
            patch(
                "src.agents.nodes.compression.make_langfuse_handler",
                return_value=mock_handler,
            ),
            patch(
                "src.agents.nodes.compression.ChunkSummarizer",
                return_value=mock_summarizer,
            ) as mock_cls,
            patch(
                "src.agents.nodes.compression._compressor"
            ) as mock_rule,
            patch(
                "src.agents.nodes.compression._get_semantic_dedup"
            ) as mock_sem_fn,
            patch(
                "src.agents.nodes.compression._get_compression_recorder",
                return_value=None,
            ),
        ):
            mock_rule.compress.return_value = ([], [])
            mock_sem_dedup = MagicMock()
            mock_sem_dedup.deduplicate.return_value = ([], [], {})
            mock_sem_fn.return_value = mock_sem_dedup

            from src.agents.nodes.compression import compression_node

            await compression_node(base_state)

        # ChunkSummarizer must be instantiated with callbacks containing the handler
        mock_cls.assert_called_once_with(callbacks=[mock_handler])
        mock_summarizer.summarize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stage3_no_callbacks_when_langfuse_disabled(
        self, base_state: dict
    ) -> None:
        """AC: SUMMARIZATION_LANGFUSE_ENABLED=false passes empty callbacks list."""
        mock_summarizer = MagicMock()
        mock_summarizer.summarize = AsyncMock(return_value=[])

        with (
            patch(
                "src.agents.nodes.compression.make_langfuse_handler",
                return_value=None,
            ),
            patch(
                "src.agents.nodes.compression.ChunkSummarizer",
                return_value=mock_summarizer,
            ) as mock_cls,
            patch(
                "src.agents.nodes.compression._compressor"
            ) as mock_rule,
            patch(
                "src.agents.nodes.compression._get_semantic_dedup"
            ) as mock_sem_fn,
            patch(
                "src.agents.nodes.compression._get_compression_recorder",
                return_value=None,
            ),
        ):
            mock_rule.compress.return_value = ([], [])
            mock_sem_dedup = MagicMock()
            mock_sem_dedup.deduplicate.return_value = ([], [], {})
            mock_sem_fn.return_value = mock_sem_dedup

            from src.agents.nodes.compression import compression_node

            await compression_node(base_state)

        # Must pass empty callbacks when handler is None
        mock_cls.assert_called_once_with(callbacks=[])

    @pytest.mark.asyncio
    async def test_all_three_stages_run_in_order(self, base_state: dict) -> None:
        """AC: compression_node runs rule-based → semantic → summarisation in order."""
        call_order: list[str] = []

        def rule_compress(chunks: list) -> tuple:
            call_order.append("rule")
            return chunks, []

        def sem_dedup(chunks: list) -> tuple:
            call_order.append("semantic")
            return chunks, [], {}

        async def summarize(chunks: list) -> list:
            call_order.append("summarization")
            return chunks

        mock_summarizer = MagicMock()
        mock_summarizer.summarize = AsyncMock(side_effect=summarize)

        with (
            patch(
                "src.agents.nodes.compression.make_langfuse_handler",
                return_value=None,
            ),
            patch(
                "src.agents.nodes.compression.ChunkSummarizer",
                return_value=mock_summarizer,
            ),
            patch(
                "src.agents.nodes.compression._compressor"
            ) as mock_rule,
            patch(
                "src.agents.nodes.compression._get_semantic_dedup"
            ) as mock_sem_fn,
            patch(
                "src.agents.nodes.compression._get_compression_recorder",
                return_value=None,
            ),
        ):
            mock_rule.compress.side_effect = rule_compress
            mock_sem_dedup = MagicMock()
            mock_sem_dedup.deduplicate.side_effect = sem_dedup
            mock_sem_fn.return_value = mock_sem_dedup

            from src.agents.nodes.compression import compression_node

            await compression_node(base_state)

        assert call_order == ["rule", "semantic", "summarization"]

    @pytest.mark.asyncio
    async def test_output_contains_compressed_context(self, base_state: dict) -> None:
        """AC: compression_node output includes compressed_context from Stage 3."""
        from datetime import datetime

        from src.retrieval.schemas.retrieved_chunk import ChunkMetadata, RetrievedChunk

        chunk = RetrievedChunk(
            chunk_id="abc123",
            source_id="src-1",
            content="Summary text",
            score=0.9,
            metadata=ChunkMetadata(
                file_path="/doc.md",
                timestamp=datetime(2025, 1, 1),
                author="bot",
            ),
        )

        mock_summarizer = MagicMock()
        mock_summarizer.summarize = AsyncMock(return_value=[chunk])

        with (
            patch(
                "src.agents.nodes.compression.make_langfuse_handler",
                return_value=None,
            ),
            patch(
                "src.agents.nodes.compression.ChunkSummarizer",
                return_value=mock_summarizer,
            ),
            patch(
                "src.agents.nodes.compression._compressor"
            ) as mock_rule,
            patch(
                "src.agents.nodes.compression._get_semantic_dedup"
            ) as mock_sem_fn,
            patch(
                "src.agents.nodes.compression._get_compression_recorder",
                return_value=None,
            ),
        ):
            mock_rule.compress.return_value = ([chunk], [])
            mock_sem_dedup = MagicMock()
            mock_sem_dedup.deduplicate.return_value = ([chunk], [], {})
            mock_sem_fn.return_value = mock_sem_dedup

            from src.agents.nodes.compression import compression_node

            result = await compression_node(base_state)

        assert result["compressed_context"] == [chunk]
        assert result["ranked_context"] == [chunk]
