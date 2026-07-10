# TASK-US032-04 — `opa_filter_node()` LangGraph Node, Prometheus Metric, and Execution Trace

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US032-04 |
| User Story | US-032 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `opa_filter_node()` LangGraph node — placed immediately after `governance_node()` (US-031) in the pipeline — that evaluates every context chunk against OPA `data.contextiq.authz.allow`, filters denied chunks (AC-3), records each decision in the execution trace (AC-4), and increments `governance_policy_denials_total` (AC-7). Satisfies AC-2 (input fields), AC-3 (filtering), AC-4 (trace), AC-5 (50 ms/chunk), AC-7 (Prometheus).

## Implementation Details

**Technology:** Python 3.11+, LangGraph `>=0.2.0`, `asyncio`, `prometheus-client>=0.20`, OpenTelemetry, Langfuse `>=2.0`

**File locations:**
- `src/governance/nodes/opa_filter_node.py` — `opa_filter_node()`
- `src/governance/opa/metrics.py` — Prometheus counters
- `src/agents/graph.py` — register node in existing `StateGraph`
- `tests/governance/test_opa_filter_node.py`

---

### Prometheus metrics

```python
# src/governance/opa/metrics.py
from prometheus_client import Counter, Histogram

# AC-7: required metric name.
governance_policy_denials_total = Counter(
    "governance_policy_denials_total",
    "Number of context chunks denied by OPA policy evaluation",
    ["tenant_id", "classification_label"],
)

opa_evaluation_duration_ms = Histogram(
    "governance_opa_evaluation_duration_ms",
    "Per-chunk OPA evaluation latency",
    ["result"],   # result: "allow" | "deny"
    buckets=[1, 5, 10, 20, 30, 50, 75, 100],
)
```

---

### `opa_filter_node()`

```python
# src/governance/nodes/opa_filter_node.py
from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

from opentelemetry import trace
from langfuse      import Langfuse
from fastapi       import Request

from src.agents.state                  import AgentState
from src.governance.opa.schemas        import ChunkAuthzInput, AuthzFilterResult
from src.governance.opa.metrics        import (
    governance_policy_denials_total, opa_evaluation_duration_ms,
)

if TYPE_CHECKING:
    from src.governance.opa.client import OPAClient

logger   = logging.getLogger(__name__)
tracer   = trace.get_tracer(__name__)
langfuse = Langfuse()


async def opa_filter_node(state: AgentState) -> AgentState:
    """
    LangGraph node — OPA Policy Enforcement Gate.

    Position: after governance_node (US-031), before model routing node.

    Steps:
    1. Build a ChunkAuthzInput per ranked_context item.
    2. Call OPAClient.evaluate_batch() concurrently.
    3. Filter out denied chunks from ranked_context.
    4. Record each decision (allow/deny + rationale) in execution_trace (AC-4).
    5. Increment governance_policy_denials_total for each denial (AC-7).
    6. Emit OTel span and Langfuse event.

    OPAClient is retrieved from app.state to allow test injection.
    If app.state.opa_client is unavailable (e.g. OPA sidecar down),
    an OPAEvaluationError propagates and blocks the request — fail-safe.
    """
    ranked_context: list[dict] = state.get("ranked_context") or []
    user_roles:  list[str]     = _extract_user_roles(state)
    tenant_id:   str           = state.get("tenant_id") or "default"

    with tracer.start_as_current_span("governance.opa_filter") as span:
        span.set_attribute("opa.chunks_to_evaluate", len(ranked_context))
        span.set_attribute("opa.tenant_id",          tenant_id)

        if not ranked_context:
            return {
                **state,
                "opa_decisions":      [],
                "opa_denied_count":   0,
                "opa_bundle_version": _get_bundle_version(state),
            }

        # Build OPA inputs
        inputs = [
            _build_authz_input(item, idx, user_roles, tenant_id)
            for idx, item in enumerate(ranked_context)
        ]

        # Evaluate — retrieved from app state (injected at lifespan startup)
        opa_client: OPAClient = _get_opa_client(state)
        bundle_version        = _get_bundle_version(state)

        filter_result: AuthzFilterResult = await opa_client.evaluate_batch(inputs)
        filter_result = AuthzFilterResult(
            **filter_result.model_dump(), bundle_version=bundle_version
        )

        # Record Prometheus metrics
        for decision in filter_result.decisions:
            label = "allow" if decision.allow else "deny"
            opa_evaluation_duration_ms.labels(result=label).observe(decision.eval_ms)

        for decision in filter_result.decisions:
            if decision.is_denied:
                # Find the original item for its classification_label
                orig = next(
                    (i for i in ranked_context
                     if str(i.get("chunk_id") or i.get("id") or "")) == decision.chunk_id,
                    None,
                )
                classification = (
                    (orig.get("metadata") or {}).get("classification_label", "internal")
                    if orig else "internal"
                )
                governance_policy_denials_total.labels(
                    tenant_id            = tenant_id,
                    classification_label = classification,
                ).inc()

        # Filter denied chunks (AC-3)
        denied_set     = set(filter_result.denied_chunk_ids)
        allowed_chunks = [
            item for idx, item in enumerate(ranked_context)
            if _chunk_key(item, idx) not in denied_set
        ]

        span.set_attribute("opa.allowed_count", len(allowed_chunks))
        span.set_attribute("opa.denied_count",  filter_result.denial_count)
        span.set_attribute("opa.eval_ms",       filter_result.total_eval_ms)

        # Record in execution_trace (AC-4)
        _record_trace(state, filter_result)

        langfuse.create_event(
            name   = "opa_policy_evaluation",
            input  = {"chunks": len(ranked_context), "tenant_id": tenant_id},
            output = {
                "allowed": len(allowed_chunks),
                "denied":  filter_result.denial_count,
                "eval_ms": filter_result.total_eval_ms,
            },
            metadata = {"bundle_version": bundle_version},
        )

        if filter_result.denial_count:
            logger.warning(
                "opa_filter_node: %d chunk(s) denied for tenant=%s. "
                "Denied IDs: %s",
                filter_result.denial_count, tenant_id,
                filter_result.denied_chunk_ids[:5],   # log max 5 to avoid log flooding
            )

        return {
            **state,
            "ranked_context":    allowed_chunks,
            "opa_decisions":     list(filter_result.decisions),
            "opa_denied_count":  filter_result.denial_count,
            "opa_bundle_version": bundle_version,
        }


# ------------------------------------------------------------------ #
# Private helpers                                                      #
# ------------------------------------------------------------------ #

def _extract_user_roles(state: AgentState) -> list[str]:
    """
    Extract user roles from the decoded JWT claims stored in AgentState.
    Falls back to empty list if not present (deny-by-default in Rego).
    """
    jwt_claims: dict = state.get("jwt_claims") or {}
    return list(jwt_claims.get("roles") or jwt_claims.get("realm_access", {}).get("roles", []))


def _build_authz_input(
    item:       dict,
    idx:        int,
    user_roles: list[str],
    tenant_id:  str,
) -> ChunkAuthzInput:
    metadata = item.get("metadata") or {}
    return ChunkAuthzInput(
        user_roles           = user_roles,
        tenant_id            = tenant_id,
        source_id            = str(item.get("source_id") or ""),
        chunk_id             = _chunk_key(item, idx),
        document_id          = str(item.get("document_id") or ""),
        classification_label = metadata.get("classification_label", "internal"),
    )


def _chunk_key(item: dict, idx: int) -> str:
    return str(item.get("chunk_id") or item.get("id") or idx)


def _get_opa_client(state: AgentState):
    """
    Retrieve OPAClient from the LangGraph config / app state.
    The configurable approach: pass OPAClient via LangGraph's `config` dict
    or retrieve from a module-level singleton for production.
    """
    from src.governance.opa.client import OPAClient
    config = state.get("_config") or {}
    return config.get("opa_client") or _DEFAULT_OPA_CLIENT


# Module-level singleton for production use (initialised at lifespan startup).
_DEFAULT_OPA_CLIENT = None


def set_opa_client(client) -> None:
    """Called from lifespan startup to inject the shared OPAClient."""
    global _DEFAULT_OPA_CLIENT
    _DEFAULT_OPA_CLIENT = client


def _get_bundle_version(state: AgentState) -> str:
    config = state.get("_config") or {}
    hot_reloader = config.get("hot_reloader")
    if hot_reloader:
        return hot_reloader.current_bundle.version
    return "unknown"


def _record_trace(state: AgentState, result: AuthzFilterResult) -> None:
    """Append OPA decisions to execution_trace (AC-4)."""
    trace_entry = {
        "node":           "opa_filter",
        "eval_ms":        result.total_eval_ms,
        "bundle_version": result.bundle_version,
        "decisions": [
            {
                "chunk_id":  d.chunk_id,
                "allow":     d.allow,
                "rationale": d.rationale,
                "eval_ms":   d.eval_ms,
            }
            for d in result.decisions
        ],
    }
    existing: list = state.get("execution_trace") or []
    state["execution_trace"] = existing + [trace_entry]
```

---

### `StateGraph` registration

```python
# src/agents/graph.py — extend existing StateGraph (do NOT replace)
from src.governance.nodes.opa_filter_node import opa_filter_node

# Place opa_filter_node after governance_node and before routing.
graph.add_node("opa_filter", opa_filter_node)
graph.add_edge("governance",  "opa_filter")
graph.add_edge("opa_filter",  "routing")
```

---

### `jwt_claims` in `AgentState`

`opa_filter_node` reads `state["jwt_claims"]` for user roles. This field is populated by the request handler before the LangGraph pipeline runs:

```python
# src/gateway/routes/query.py — existing route handler (extend only)
state = AgentState(
    query      = request.query,
    jwt_claims = request.state.jwt_claims,   # set by JWT middleware
    tenant_id  = request.state.tenant_id,
    # …
)
```

## Acceptance Criteria

- [ ] `opa_filter_node` calls `OPAClient.evaluate_batch()` with one `ChunkAuthzInput` per ranked_context item
- [ ] All four required fields (`user_roles`, `tenant_id`, `source_id`, `classification_label`) are present in each `ChunkAuthzInput`
- [ ] Denied chunks are absent from `ranked_context` in the returned state (AC-3)
- [ ] Allowed chunks are present and in their original order (AC-3)
- [ ] `execution_trace` contains an `"opa_filter"` entry with per-chunk decisions (AC-4)
- [ ] `governance_policy_denials_total` counter is incremented for each denied chunk (AC-7)
- [ ] Empty `ranked_context` returns immediately without calling `OPAClient`
- [ ] `OPAEvaluationError` propagates to the caller (fail-safe; does not silently allow)

## Dependencies

- TASK-US032-01 (`ChunkAuthzInput`, `PolicyDecision`, `AuthzFilterResult`)
- TASK-US032-02 (`OPAClient`, `OPAEvaluationError`)
- TASK-US032-03 (`PolicyHotReloader.current_bundle.version`)
- TASK-US031-04 (`governance_node` — `opa_filter_node` is placed after it)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests inject `OPAClient` mock via `state["_config"]["opa_client"]` — no live OPA in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
