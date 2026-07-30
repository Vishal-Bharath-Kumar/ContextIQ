"""Tests for EdgeInferenceEngine — TASK-US030-02.

Covers all acceptance criteria:
  AC-1  infer() with a single entity returns [].
  AC-2  infer() with two entities and use_llm=False returns exactly one REFERENCES edge.
  AC-3  infer() with three entities and use_llm=False returns exactly three REFERENCES edges.
  AC-4  LLM-typed edge for pair (A→B) suppresses the heuristic REFERENCES edge for the same pair.
  AC-5  LLM asyncio.TimeoutError falls back to heuristic edges (no exception propagated).
  AC-6  LLM returning an entity name not in the chunk is silently skipped.
  AC-7  weight < min_weight edges from LLM are filtered out.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.knowledge_graph.inference.edge_inference_engine import (
    EdgeInferenceEngine,
    EdgeInferenceSettings,
)
from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.schemas.entity import (
    EntityExtractionResult,
    EntityType,
    ExtractedEntity,
    make_entity_id,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHUNK_ID = UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(name: str, entity_type: EntityType = EntityType.SERVICE) -> ExtractedEntity:
    return ExtractedEntity(
        entity_id=make_entity_id(entity_type, name),
        entity_type=entity_type,
        name=name,
        canonical_name=name.strip().lower(),
        source_id=_SOURCE_ID,
        chunk_id=_CHUNK_ID,
        created_at=datetime.now(tz=UTC),
    )


def _make_result(entities: list[ExtractedEntity]) -> EntityExtractionResult:
    return EntityExtractionResult(
        chunk_id=_CHUNK_ID,
        source_id=_SOURCE_ID,
        entities=entities,
        duration_ms=1.0,
    )


def _make_litellm_response(content: str) -> MagicMock:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    response = MagicMock()
    response.choices = [choice]
    return response


def _no_llm_settings(**kwargs: object) -> EdgeInferenceSettings:
    return EdgeInferenceSettings(use_llm=False, **kwargs)


def _llm_settings(**kwargs: object) -> EdgeInferenceSettings:
    return EdgeInferenceSettings(use_llm=True, model_id="ollama/llama3.2", **kwargs)


# ---------------------------------------------------------------------------
# AC-1 — single entity → empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_infer_single_entity_returns_empty() -> None:
    engine = EdgeInferenceEngine(settings=_no_llm_settings())
    result = _make_result([_make_entity("AuthService")])
    edges = await engine.infer(result, "AuthService handles requests.")
    assert edges == []


# ---------------------------------------------------------------------------
# AC-2 — two entities, no LLM → exactly one REFERENCES edge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_infer_two_entities_no_llm_returns_one_references_edge() -> None:
    engine = EdgeInferenceEngine(settings=_no_llm_settings())
    e1 = _make_entity("AuthService")
    e2 = _make_entity("UserService")
    result = _make_result([e1, e2])

    edges = await engine.infer(result, "AuthService and UserService communicate.")

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.REFERENCES
    assert {edges[0].from_entity_id, edges[0].to_entity_id} == {e1.entity_id, e2.entity_id}


# ---------------------------------------------------------------------------
# AC-3 — three entities, no LLM → exactly three REFERENCES edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_infer_three_entities_no_llm_returns_three_references_edges() -> None:
    engine = EdgeInferenceEngine(settings=_no_llm_settings())
    entities = [_make_entity("A"), _make_entity("B"), _make_entity("C")]
    result = _make_result(entities)

    edges = await engine.infer(result, "A, B and C co-exist in this chunk.")

    assert len(edges) == 3
    assert all(e.edge_type == EdgeType.REFERENCES for e in edges)


# ---------------------------------------------------------------------------
# AC-4 — LLM typed edge suppresses heuristic REFERENCES for same pair
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_typed_edge_suppresses_heuristic_references_for_same_pair() -> None:
    e1 = _make_entity("AuthService")
    e2 = _make_entity("UserDB")
    result = _make_result([e1, e2])

    llm_payload = json.dumps({
        "relationships": [
            {"from": "AuthService", "to": "UserDB", "type": "DEPENDS_ON", "weight": 0.9}
        ]
    })
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        engine = EdgeInferenceEngine(settings=_llm_settings())
        edges = await engine.infer(result, "AuthService depends on UserDB.")

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.DEPENDS_ON
    assert edges[0].from_entity_id == e1.entity_id
    assert edges[0].to_entity_id == e2.entity_id


# ---------------------------------------------------------------------------
# AC-5 — LLM TimeoutError falls back to heuristic (no exception propagated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_timeout_falls_back_to_heuristic_edges() -> None:
    e1 = _make_entity("Alpha")
    e2 = _make_entity("Beta")
    result = _make_result([e1, e2])

    with patch("litellm.acompletion", new=AsyncMock(side_effect=TimeoutError())):
        engine = EdgeInferenceEngine(settings=_llm_settings())
        # Must not raise; must return the heuristic REFERENCES edge
        edges = await engine.infer(result, "Alpha and Beta coexist.")

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.REFERENCES


@pytest.mark.asyncio
async def test_llm_generic_exception_falls_back_to_heuristic_edges() -> None:
    e1 = _make_entity("Alpha")
    e2 = _make_entity("Beta")
    result = _make_result([e1, e2])

    with patch(
        "litellm.acompletion", new=AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    ):
        engine = EdgeInferenceEngine(settings=_llm_settings())
        edges = await engine.infer(result, "Alpha and Beta coexist.")

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.REFERENCES


# ---------------------------------------------------------------------------
# AC-6 — LLM returns unknown entity name → silently skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_unknown_entity_name_is_skipped() -> None:
    e1 = _make_entity("AuthService")
    e2 = _make_entity("UserService")
    result = _make_result([e1, e2])

    # "GhostService" is not in the chunk
    llm_payload = json.dumps({
        "relationships": [
            {"from": "AuthService", "to": "GhostService", "type": "DEPENDS_ON", "weight": 0.9}
        ]
    })
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        engine = EdgeInferenceEngine(settings=_llm_settings())
        edges = await engine.infer(result, "AuthService and UserService.")

    # Unknown entity skipped → only the heuristic REFERENCES edge remains
    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.REFERENCES


# ---------------------------------------------------------------------------
# AC-7 — weight < min_weight edges are filtered out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_low_weight_edge_is_filtered_out() -> None:
    e1 = _make_entity("AuthService")
    e2 = _make_entity("UserService")
    result = _make_result([e1, e2])

    # weight=0.3 is below the default min_weight=0.5
    llm_payload = json.dumps({
        "relationships": [
            {"from": "AuthService", "to": "UserService", "type": "DEPENDS_ON", "weight": 0.3}
        ]
    })
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        engine = EdgeInferenceEngine(settings=_llm_settings(min_weight=0.5))
        edges = await engine.infer(result, "AuthService and UserService.")

    # Low-weight LLM edge filtered → only the heuristic REFERENCES edge
    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.REFERENCES


# ---------------------------------------------------------------------------
# Additional: LLM returns empty relationships → heuristic edges kept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_empty_relationships_keeps_heuristic_edges() -> None:
    e1 = _make_entity("ServiceA")
    e2 = _make_entity("ServiceB")
    result = _make_result([e1, e2])

    llm_payload = json.dumps({"relationships": []})
    mock_response = _make_litellm_response(llm_payload)

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_response)):
        engine = EdgeInferenceEngine(settings=_llm_settings())
        edges = await engine.infer(result, "ServiceA and ServiceB are mentioned.")

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.REFERENCES


# ---------------------------------------------------------------------------
# Additional: heuristic edge metadata is correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heuristic_edge_metadata() -> None:
    e1 = _make_entity("AuthService")
    e2 = _make_entity("UserService")
    result = _make_result([e1, e2])

    engine = EdgeInferenceEngine(settings=_no_llm_settings())
    edges = await engine.infer(result, "chunk text")

    edge = edges[0]
    assert edge.chunk_id == _CHUNK_ID
    assert edge.source_id == _SOURCE_ID
    assert edge.weight == 0.5


# ---------------------------------------------------------------------------
# AC-4 — Throughput: 500 chunks via heuristic-only path (fast path benchmark)
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
def test_edge_inference_heuristic_500_chunks_benchmark(benchmark: pytest.FixtureRequest) -> None:
    """500 chunks through the heuristic path must complete in < 5 s mean.

    Excluded from the default CI run (use ``-m 'not benchmark'``).
    Run with: pytest --benchmark-only tests/knowledge_graph/test_edge_inference_engine.py
    """
    import asyncio

    engine = EdgeInferenceEngine(settings=_no_llm_settings())
    e1 = _make_entity("AuthService")
    e2 = _make_entity("UserService")
    result = _make_result([e1, e2])

    def run_all_500() -> None:
        async def _inner() -> None:
            for _ in range(500):
                await engine.infer(result, "chunk text")

        asyncio.run(_inner())

    benchmark(run_all_500)
    assert benchmark.stats["mean"] < 5.0, (
        f"500 chunks (heuristic path) took {benchmark.stats['mean']:.2f}s — must be < 5s"
    )
