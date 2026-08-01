"""End-to-End Pipeline SLA Benchmark — TASK-US006-05.

Validates that the ContextIQ multi-agent pipeline meets its p95 latency SLA
using calibrated stub nodes that sleep for realistic sub-agent durations.

SLA targets
-----------
  Full path  (intent → retrieval → governance → compression → routing): p95 < 3 s
  Skip path  (intent → retrieval → governance → routing):               p95 < 2 s

Benchmark strategy
------------------
Tests are marked ``benchmark`` and are **excluded from the default pytest run**.
They execute only when:

    pytest -m benchmark tests/agents/test_pipeline_sla.py

Each benchmark uses 100 rounds + 10 warmup rounds to produce a statistically
stable sample.  The p95 is derived from the raw timing data collected by
pytest-benchmark (``benchmark.stats["data"]`` in the installed plugin).

Async handling
--------------
``pytest-benchmark`` runs callables synchronously.  Each benchmark callable
creates a dedicated ``asyncio`` event loop so that ``ainvoke`` can be called
without nesting inside the pytest-asyncio managed loop.
"""
from __future__ import annotations

import asyncio
import statistics
from uuid import uuid4

import pytest

from src.agents.state import AgentState, ExecutionStatus
from tests.agents.stubs.latency_nodes import build_stub_graph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_initial_state(prompt: str) -> AgentState:
    """Return a minimal valid ``AgentState`` for benchmark invocations."""
    return {
        "request_id": str(uuid4()),
        "user_id": "bench-user",
        "username": "benchmarker",
        "roles": ["developer"],
        "tool_name": "context_search",
        "prompt": prompt,
        "timestamp": "2026-01-01T00:00:00Z",
        "status": ExecutionStatus.PENDING,
        "current_node": "",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "execution_plan": None,
        "raw_context": None,
        "ranked_context": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }


def _p95(data: list[float]) -> float:
    """Return the 95th percentile of *data* (timings in seconds)."""
    return statistics.quantiles(data, n=100)[94]


# ---------------------------------------------------------------------------
# Benchmark: full path (with compression)
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="e2e-pipeline")
@pytest.mark.timeout(300)  # 100 rounds × ~1.4 s + warmup ≈ 150 s; override global 120 s limit
def test_pipeline_p95_under_3s(benchmark) -> None:
    """Full pipeline (with compression) must complete at p95 < 3 s.

    Latency budget:
      intent (200 ms) + retrieval (800 ms) + governance (100 ms)
      + compression (200 ms) + routing (50 ms) = 1 350 ms median
    Expected p95 ≈ 1 350 ms — well within the 3 000 ms SLA.
    """
    stub_graph = build_stub_graph(compression_skip=False)
    initial_state = _make_initial_state(prompt="Why is service X slow?")
    loop = asyncio.new_event_loop()

    def _run_pipeline() -> AgentState:
        config = {"configurable": {"thread_id": str(uuid4())}}
        return loop.run_until_complete(stub_graph.ainvoke(initial_state, config=config))

    try:
        result: AgentState = benchmark.pedantic(
            _run_pipeline,
            rounds=100,
            warmup_rounds=10,
        )
    finally:
        loop.close()

    p95 = _p95(list(benchmark.stats["data"]))
    assert p95 < 3.0, f"p95 latency {p95:.3f} s exceeds 3 s SLA (full path)"
    assert result["status"] == ExecutionStatus.COMPLETE
    assert result["final_response"] is not None


# ---------------------------------------------------------------------------
# Benchmark: skip-compression path
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="e2e-pipeline")
@pytest.mark.timeout(300)  # 100 rounds × ~1.2 s + warmup ≈ 132 s; override global 120 s limit
def test_pipeline_skip_compression_p95_under_2s(benchmark) -> None:
    """Pipeline without compression must complete at p95 < 2 s.

    Latency budget:
      intent (200 ms) + retrieval (800 ms) + governance (100 ms)
      + routing (50 ms) = 1 150 ms median
    Expected p95 ≈ 1 150 ms — well within the 2 000 ms SLA.
    """
    stub_graph = build_stub_graph(compression_skip=True)
    initial_state = _make_initial_state(prompt="How do I fix the memory leak?")
    loop = asyncio.new_event_loop()

    def _run_pipeline() -> AgentState:
        config = {"configurable": {"thread_id": str(uuid4())}}
        return loop.run_until_complete(stub_graph.ainvoke(initial_state, config=config))

    try:
        result: AgentState = benchmark.pedantic(
            _run_pipeline,
            rounds=100,
            warmup_rounds=10,
        )
    finally:
        loop.close()

    p95 = _p95(list(benchmark.stats["data"]))
    assert p95 < 2.0, f"p95 latency {p95:.3f} s exceeds 2 s SLA (skip-compression path)"
    assert result["status"] == ExecutionStatus.COMPLETE
    assert result["final_response"] is not None


# ---------------------------------------------------------------------------
# Latency model unit test (fast, non-benchmark)
# ---------------------------------------------------------------------------


def test_latency_model_sums_under_sla() -> None:
    """Mathematical validation: node medians sum to < 3 s budget."""
    node_medians_ms = {
        "intent_agent": 200,
        "retrieval_agent": 800,
        "governance_agent": 100,
        "compression_agent": 200,
        "routing_agent": 50,
    }
    full_path_ms = sum(node_medians_ms.values())
    skip_path_ms = full_path_ms - node_medians_ms["compression_agent"]

    assert full_path_ms < 3000, f"Full-path median {full_path_ms} ms exceeds 3 s budget"
    assert skip_path_ms < 2000, f"Skip-path median {skip_path_ms} ms exceeds 2 s budget"


# ---------------------------------------------------------------------------
# Prometheus histogram registration test (fast, non-benchmark)
# ---------------------------------------------------------------------------


def test_pipeline_e2e_histogram_registered() -> None:
    """``contextiq_pipeline_e2e_duration_seconds`` must be registered with path label."""
    from prometheus_client import REGISTRY

    from src.agents.telemetry import pipeline_e2e_duration  # noqa: PLC0415

    # Verify the histogram is retrievable from the Prometheus registry.
    metric_families = {mf.name: mf for mf in REGISTRY.collect()}
    assert "contextiq_pipeline_e2e_duration_seconds" in metric_families

    # Record a sample observation to confirm the path label is accepted.
    pipeline_e2e_duration.labels(path="full").observe(1.35)
    pipeline_e2e_duration.labels(path="skip_compression").observe(1.15)
    pipeline_e2e_duration.labels(path="clarification").observe(0.25)
    pipeline_e2e_duration.labels(path="failed").observe(0.40)
