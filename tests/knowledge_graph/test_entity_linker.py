"""Tests for EntityLinker — TASK-US029-02.

Covers all acceptance criteria:
  AC-1  Fast path: metadata.entity_ids present → returned without LLM call.
  AC-2  Fast path: duplicates deduplicated in insertion order.
  AC-3  Fast path: result capped at max_seeds.
  AC-4  Slow path: asyncio.TimeoutError caught; resolve() returns [].
  AC-5  Slow path: JSON parse failure caught; resolve() returns [].
  Slow path happy path: LLM names resolved via GraphTraversalClient lookup.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.knowledge_graph.traversal.entity_linker import EntityLinker, EntityLinkerSettings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides: object) -> EntityLinkerSettings:
    defaults: dict = {
        "model_id": "ollama/llama3.2",
        "temperature": 0.0,
        "max_tokens": 256,
        "timeout_s": 1.0,
        "max_seeds": 10,
    }
    defaults.update(overrides)
    return EntityLinkerSettings(**defaults)


def _make_litellm_response(content: str) -> MagicMock:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_client(lookup_return: list[str] | None = None) -> MagicMock:
    client = MagicMock()
    client.lookup_entity_ids = AsyncMock(return_value=lookup_return or [])
    return client


def _item(text: str = "some text", entity_ids: list[str] | None = None) -> dict:
    metadata: dict = {}
    if entity_ids is not None:
        metadata["entity_ids"] = entity_ids
    return {"text": text, "score": 0.9, "source_id": "src-1", "metadata": metadata}


# ---------------------------------------------------------------------------
# AC-1 — Fast path: metadata.entity_ids used; no LLM call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_returns_entity_ids_without_llm() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(entity_ids=["id-1", "id-2"])]

    with patch("litellm.acompletion") as mock_llm:
        result = await linker.resolve(ctx)

    assert result == ["id-1", "id-2"]
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_no_client_lookup_called() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(entity_ids=["id-a"])]

    await linker.resolve(ctx)

    client.lookup_entity_ids.assert_not_called()


# ---------------------------------------------------------------------------
# AC-2 — Fast path: duplicates across items deduplicated in insertion order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_deduplicates_preserving_insertion_order() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [
        _item(entity_ids=["id-1", "id-2"]),
        _item(entity_ids=["id-2", "id-3"]),
        _item(entity_ids=["id-1", "id-4"]),
    ]

    result = await linker.resolve(ctx)

    assert result == ["id-1", "id-2", "id-3", "id-4"]


# ---------------------------------------------------------------------------
# AC-3 — Fast path: result capped at max_seeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_capped_at_max_seeds() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings(max_seeds=3))
    ids = [f"id-{i}" for i in range(8)]
    ctx = [_item(entity_ids=ids)]

    result = await linker.resolve(ctx)

    assert result == ["id-0", "id-1", "id-2"]
    assert len(result) == 3


# ---------------------------------------------------------------------------
# AC-1 — Fast path triggered even when some items have no metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_path_mixed_items_with_and_without_entity_ids() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [
        _item(text="no ids here"),  # no entity_ids key
        _item(entity_ids=["id-x"]),
    ]

    with patch("litellm.acompletion") as mock_llm:
        result = await linker.resolve(ctx)

    assert result == ["id-x"]
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_fast_path_item_with_none_metadata() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [
        {"text": "x", "score": 0.5, "source_id": "s", "metadata": None},
        _item(entity_ids=["id-y"]),
    ]

    result = await linker.resolve(ctx)

    assert result == ["id-y"]


# ---------------------------------------------------------------------------
# Slow path — happy path: LLM extracts names, client resolves IDs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_path_llm_names_resolved_to_ids() -> None:
    client = _make_client(lookup_return=["neo4j-id-1", "neo4j-id-2"])
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(text="auth-service and user-repo are involved")]

    llm_payload = json.dumps({"entity_names": ["auth-service", "user-repo"]})
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await linker.resolve(ctx)

    client.lookup_entity_ids.assert_awaited_once_with(["auth-service", "user-repo"])
    assert result == ["neo4j-id-1", "neo4j-id-2"]


@pytest.mark.asyncio
async def test_slow_path_capped_at_max_seeds() -> None:
    client = _make_client(lookup_return=[f"id-{i}" for i in range(15)])
    linker = EntityLinker(traversal_client=client, settings=_settings(max_seeds=5))
    ctx = [_item(text="lots of services")]

    llm_payload = json.dumps({"entity_names": ["svc"]})
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await linker.resolve(ctx)

    assert len(result) == 5


# ---------------------------------------------------------------------------
# AC-4 — Slow path: asyncio.TimeoutError → resolve() returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_path_timeout_returns_empty_list() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(text="trigger slow path")]

    with patch("litellm.acompletion", new=AsyncMock(side_effect=asyncio.TimeoutError)):
        result = await linker.resolve(ctx)

    assert result == []
    client.lookup_entity_ids.assert_not_called()


# ---------------------------------------------------------------------------
# AC-5 — Slow path: JSON parse failure → resolve() returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_path_invalid_json_returns_empty_list() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(text="trigger slow path")]

    mock_response = _make_litellm_response("not valid json {{ }")

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await linker.resolve(ctx)

    assert result == []
    client.lookup_entity_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Slow path: empty entity_names from LLM → resolve() returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_path_empty_entity_names_returns_empty_list() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(text="nothing specific")]

    llm_payload = json.dumps({"entity_names": []})
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await linker.resolve(ctx)

    assert result == []
    client.lookup_entity_ids.assert_not_called()


# ---------------------------------------------------------------------------
# Slow path: general LLM exception → resolve() returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_path_generic_exception_returns_empty_list() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())
    ctx = [_item(text="trigger slow path")]

    with patch("litellm.acompletion", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = await linker.resolve(ctx)

    assert result == []


# ---------------------------------------------------------------------------
# Empty ranked_context → resolve() returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ranked_context_returns_empty_list() -> None:
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())

    llm_payload = json.dumps({"entity_names": []})
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        result = await linker.resolve([])

    assert result == []


# ---------------------------------------------------------------------------
# TASK-US029-05 — AC-1 named tests (fast path + slow path)
# ---------------------------------------------------------------------------

_US029_SEED_ID = "a3f1c2b4d5e6f708"


@pytest.mark.asyncio
async def test_entity_linker_fast_path_skips_llm(
    ranked_context_with_entity_ids: list,
) -> None:
    """AC-1 fast path: metadata.entity_ids present → returned without any LLM call."""
    client = _make_client()
    linker = EntityLinker(traversal_client=client, settings=_settings())

    with patch("litellm.acompletion") as mock_llm:
        seeds = await linker.resolve(ranked_context_with_entity_ids)

    assert seeds == [_US029_SEED_ID]
    mock_llm.assert_not_called()
    client.lookup_entity_ids.assert_not_called()


@pytest.mark.asyncio
async def test_entity_linker_slow_path_on_no_entity_ids(
    ranked_context_no_entity_ids: list,
) -> None:
    """AC-1 slow path: no metadata.entity_ids → LLM extracts names → client resolves IDs."""
    client = _make_client(lookup_return=[_US029_SEED_ID])
    linker = EntityLinker(traversal_client=client, settings=_settings())

    llm_payload = json.dumps({"entity_names": ["auth-service"]})
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        seeds = await linker.resolve(ranked_context_no_entity_ids)

    client.lookup_entity_ids.assert_awaited_once_with(["auth-service"])
    assert seeds == [_US029_SEED_ID]
