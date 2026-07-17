"""Integration tests for LLMCostRecorder — AC-1 and AC-4 (TASK-US037-05).

Coverage:
  - AC-1: record_llm_call passes all six required fields in Langfuse metadata
  - AC-1: recorder silently handles Langfuse SDK exceptions (fire-and-forget)
  - AC-2: record_compression passes both token fields in Langfuse event metadata
  - AC-4: metadata dict has all six AC-1 keys as top-level keys (queryable)
"""

from __future__ import annotations

import pytest

from src.observability.cost.recorder import LLMCostRecorder
from tests.observability.conftest import (
    SAMPLE_COMPRESSION_RECORD,
    SAMPLE_LLM_RECORD,
    TEAM_ID,
    USER_ID,
)


# ---------------------------------------------------------------------------
# AC-1: Langfuse records all six required LLM call fields
# ---------------------------------------------------------------------------


def test_record_llm_call_sends_all_six_ac1_fields(mock_langfuse):
    """AC-1: all six required metadata fields present in langfuse.generation() call."""
    recorder = LLMCostRecorder()
    recorder.record_llm_call(SAMPLE_LLM_RECORD)

    mock_langfuse.generation.assert_called_once()
    call_kwargs = mock_langfuse.generation.call_args.kwargs
    metadata = call_kwargs.get("metadata", {})

    assert metadata["model_id"] == "gpt-4o"
    assert metadata["prompt_tokens"] == 512
    assert metadata["completion_tokens"] == 128
    assert metadata["cost_usd"] == 0.00480
    assert metadata["user_id"] == USER_ID
    assert metadata["team_id"] == TEAM_ID


def test_record_llm_call_does_not_raise_on_langfuse_error(mock_langfuse):
    """AC-1: recorder silently handles Langfuse SDK exceptions."""
    mock_langfuse.generation.side_effect = RuntimeError("Langfuse down")
    recorder = LLMCostRecorder()
    # Must not raise
    recorder.record_llm_call(SAMPLE_LLM_RECORD)


# ---------------------------------------------------------------------------
# AC-2: compression record passes both token fields
# ---------------------------------------------------------------------------


def test_compression_langfuse_event_contains_both_token_fields(mock_langfuse):
    """AC-2: langfuse.event() metadata includes tokens_before and tokens_after."""
    recorder = LLMCostRecorder()
    recorder.record_compression(SAMPLE_COMPRESSION_RECORD)

    mock_langfuse.event.assert_called_once()
    metadata = mock_langfuse.event.call_args.kwargs.get("metadata", {})
    assert metadata["tokens_before_compression"] == 800
    assert metadata["tokens_after_compression"] == 400
    assert metadata["savings_pct"] == 50.0


# ---------------------------------------------------------------------------
# AC-4: metadata structure is queryable (all six keys at top level)
# ---------------------------------------------------------------------------


def test_langfuse_generation_metadata_is_queryable_by_all_six_fields(mock_langfuse):
    """
    AC-4: The metadata dict passed to langfuse.generation() contains each of the
    six AC-1 fields as top-level keys — enabling Langfuse API filtering by any of them.
    """
    recorder = LLMCostRecorder()
    recorder.record_llm_call(SAMPLE_LLM_RECORD)

    metadata = mock_langfuse.generation.call_args.kwargs["metadata"]
    required_keys = {
        "model_id",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "user_id",
        "team_id",
    }
    assert required_keys.issubset(set(metadata.keys()))
