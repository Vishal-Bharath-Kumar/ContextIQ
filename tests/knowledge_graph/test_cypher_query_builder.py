"""Tests for CypherQueryBuilder and traversal schemas — TASK-US029-01.

Covers all acceptance criteria:
  AC-1  build_traversal() produces *1..3 for max_depth=3.
  AC-2  build_traversal() produces *1..5 for max_depth=5.
  AC-3  All external inputs (seed_ids, edge_types, limit) are in params dict,
        never interpolated into the query string.
  AC-4  TraversalConfig with seed_entity_ids=[] raises ValidationError.
  AC-5  GraphContextItem.source is always "knowledge_graph".
  AC-6  GraphTraversalResult.truncated defaults to False.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.knowledge_graph.schemas.edge import EdgeType
from src.knowledge_graph.traversal.query_builder import CypherQueryBuilder
from src.knowledge_graph.traversal.schemas import (
    GraphContextItem,
    GraphTraversalResult,
    TraversalConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEED_IDS = ["entity-001", "entity-002"]
_BUDGET = 512


def _config(**overrides: object) -> TraversalConfig:
    defaults: dict = {
        "seed_entity_ids": _SEED_IDS,
        "token_budget": _BUDGET,
    }
    defaults.update(overrides)
    return TraversalConfig(**defaults)


def _builder() -> CypherQueryBuilder:
    return CypherQueryBuilder()


# ---------------------------------------------------------------------------
# AC-1 — depth=3 produces *1..3 literal
# ---------------------------------------------------------------------------


def test_build_traversal_depth_3_literal() -> None:
    query, _ = _builder().build_traversal(_config(max_depth=3))
    assert "*1..3" in query


# ---------------------------------------------------------------------------
# AC-2 — depth=5 produces *1..5 literal
# ---------------------------------------------------------------------------


def test_build_traversal_depth_5_literal() -> None:
    query, _ = _builder().build_traversal(_config(max_depth=5))
    assert "*1..5" in query


# ---------------------------------------------------------------------------
# AC-3 — external inputs in params, not in query string
# ---------------------------------------------------------------------------


def test_build_traversal_seed_ids_in_params_not_query() -> None:
    query, params = _builder().build_traversal(_config())
    # seed_ids must be a parameter key
    assert "seed_ids" in params
    assert params["seed_ids"] == _SEED_IDS
    # no literal seed value should appear in query string
    for seed in _SEED_IDS:
        assert seed not in query


def test_build_traversal_edge_types_in_params_not_query() -> None:
    edge_types = [EdgeType.DEPENDS_ON, EdgeType.OWNED_BY]
    query, params = _builder().build_traversal(_config(edge_types=edge_types))
    assert "edge_types" in params
    assert set(params["edge_types"]) == {"DEPENDS_ON", "OWNED_BY"}
    # raw edge type values must not be interpolated literally (only $edge_types ref)
    assert "$edge_types" in query


def test_build_traversal_limit_in_params_not_query() -> None:
    query, params = _builder().build_traversal(_config(max_nodes_per_seed=10))
    assert "limit" in params
    expected_limit = 10 * len(_SEED_IDS)
    assert params["limit"] == expected_limit
    assert "$limit" in query


def test_build_traversal_params_keys_complete() -> None:
    _, params = _builder().build_traversal(_config())
    assert set(params.keys()) == {"seed_ids", "edge_types", "limit"}


# ---------------------------------------------------------------------------
# AC-4 — empty seed_entity_ids raises ValidationError
# ---------------------------------------------------------------------------


def test_traversal_config_empty_seeds_raises() -> None:
    with pytest.raises(ValidationError):
        TraversalConfig(seed_entity_ids=[], token_budget=_BUDGET)


# ---------------------------------------------------------------------------
# AC-5 — GraphContextItem.source is always "knowledge_graph"
# ---------------------------------------------------------------------------


def test_graph_context_item_source_default() -> None:
    item = GraphContextItem(
        entity_id="e1",
        entity_type="Service",
        name="auth-service",
        hops=1,
        path_summary="seed -[DEPENDS_ON]-> auth-service",
        token_count=10,
    )
    assert item.source == "knowledge_graph"


def test_graph_context_item_source_cannot_be_overridden_implicitly() -> None:
    # source field has a fixed default; passing another value must still store it
    # (Pydantic does not prevent assignment at construction; this test validates
    # the *default* is correct for all items that do not override it).
    item = GraphContextItem(
        entity_id="e2",
        entity_type="Repository",
        name="user-repo",
        hops=2,
        path_summary="seed -[OWNED_BY]-> user-repo",
        token_count=8,
    )
    assert item.source == "knowledge_graph"


# ---------------------------------------------------------------------------
# AC-6 — GraphTraversalResult.truncated defaults to False
# ---------------------------------------------------------------------------


def test_graph_traversal_result_truncated_defaults_false() -> None:
    result = GraphTraversalResult(
        items=[],
        total_tokens=0,
        query_duration_ms=12.5,
        seeds_used=["entity-001"],
    )
    assert result.truncated is False


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_build_traversal_all_edge_types_present_by_default() -> None:
    _, params = _builder().build_traversal(_config())
    assert set(params["edge_types"]) == {
        "DEPENDS_ON",
        "OWNED_BY",
        "HAS_INCIDENT",
        "DEPLOYED_BY",
        "REFERENCES",
    }


def test_build_traversal_query_starts_with_match() -> None:
    query, _ = _builder().build_traversal(_config())
    assert query.startswith("MATCH")


def test_build_entity_lookup_params_key() -> None:
    builder = _builder()
    entity_ids = ["e1", "e2", "e3"]
    query, params = builder.build_entity_lookup(entity_ids)
    assert "entity_ids" in params
    assert params["entity_ids"] == entity_ids
    assert "$entity_ids" in query


def test_traversal_config_max_depth_boundary_ge_1() -> None:
    with pytest.raises(ValidationError):
        TraversalConfig(seed_entity_ids=["e1"], token_budget=100, max_depth=0)


def test_traversal_config_max_depth_boundary_le_5() -> None:
    with pytest.raises(ValidationError):
        TraversalConfig(seed_entity_ids=["e1"], token_budget=100, max_depth=6)


def test_traversal_config_frozen() -> None:
    config = _config()
    with pytest.raises((TypeError, ValidationError)):
        config.max_depth = 4  # type: ignore[misc]


def test_graph_context_item_frozen() -> None:
    item = GraphContextItem(
        entity_id="e1",
        entity_type="Service",
        name="svc",
        hops=1,
        path_summary="a -[X]-> b",
        token_count=5,
    )
    with pytest.raises((TypeError, ValidationError)):
        item.hops = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TASK-US029-05 — AC-2/AC-3 named tests
# ---------------------------------------------------------------------------

_US029_SEED_ID = "a3f1c2b4d5e6f708"


def test_traversal_config_includes_all_five_edge_types() -> None:
    """AC-2: Default TraversalConfig.edge_types contains exactly all 5 EdgeType values."""
    config = TraversalConfig(seed_entity_ids=[_US029_SEED_ID], token_budget=1000)
    assert set(config.edge_types) == set(EdgeType)


def test_cypher_query_contains_edge_types_as_parameter() -> None:
    """AC-2: Edge types must be in params ($edge_types), never interpolated into query string."""
    config = TraversalConfig(seed_entity_ids=[_US029_SEED_ID], token_budget=1000)
    query, params = CypherQueryBuilder().build_traversal(config)

    assert "$edge_types" in query
    assert "DEPENDS_ON" not in query
    assert "DEPENDS_ON" in params["edge_types"]


def test_cypher_query_uses_max_depth_as_literal() -> None:
    """AC-3: Depth bound appears as *1..<depth> literal in the Cypher query."""
    for depth in (1, 2, 3, 5):
        config = TraversalConfig(
            seed_entity_ids=[_US029_SEED_ID], token_budget=1000, max_depth=depth
        )
        query, _ = CypherQueryBuilder().build_traversal(config)
        assert f"*1..{depth}" in query, f"*1..{depth} not found in query for depth={depth}"


def test_traversal_config_rejects_depth_above_five() -> None:
    """AC-3: TraversalConfig with max_depth > 5 raises a ValidationError."""
    with pytest.raises(ValidationError):
        TraversalConfig(seed_entity_ids=[_US029_SEED_ID], token_budget=1000, max_depth=6)
