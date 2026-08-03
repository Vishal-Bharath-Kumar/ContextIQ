# TASK-US031-04 — `governance_node()` LangGraph Node, `AgentState` Extensions, and Audit Trace

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US031-04 |
| User Story | US-031 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `governance_node()` LangGraph node — the mandatory pipeline gate that runs `SecretPIIDetector` and `ContextRedactor` on assembled context, records all findings in the execution trace (AC-7), and either passes redacted context forward or raises a hard error on timeout (fail-safe). Extend `AgentState` with governance-specific fields. Register the node between the compression node and the routing node in the existing `StateGraph`. Satisfies AC-1, AC-4, AC-5, AC-7.

## Implementation Details

**Technology:** Python 3.11+, LangGraph `>=0.2.0`, Pydantic v2, OpenTelemetry, Langfuse `>=2.0`

**File locations:**
- `src/agents/state.py` — extend existing `AgentState` TypedDict
- `src/governance/nodes/governance_node.py` — `governance_node()`
- `src/agents/graph.py` — register node in existing `StateGraph`
- `tests/governance/test_governance_node.py`

---

### `AgentState` extensions

```python
# src/agents/state.py  — extend existing TypedDict (do NOT replace)
from typing import TypedDict, NotRequired
from src.governance.schemas.finding import DetectionFinding, GovernanceScanResult

class AgentState(TypedDict):
    # … existing fields (query, ranked_context, execution_plan,
    #   graph_context_items, graph_traversal_skipped, …) …

    # New fields added by governance_node:
    governance_findings:   NotRequired[list[DetectionFinding]]
    context_redacted:      NotRequired[bool]
    governance_scan_ms:    NotRequired[float]
    # True when the node was blocked by a scan timeout (fail-safe active).
    governance_blocked:    NotRequired[bool]
```

---

### `governance_node()`

```python
# src/governance/nodes/governance_node.py
from __future__ import annotations
import logging
from opentelemetry import trace
from langfuse      import Langfuse

from src.agents.state                          import AgentState
from src.governance.detection.detector         import SecretPIIDetector, GovernanceScanTimeoutError
from src.governance.detection.redactor         import ContextRedactor

logger   = logging.getLogger(__name__)
tracer   = trace.get_tracer(__name__)
langfuse = Langfuse()

_DETECTOR = SecretPIIDetector()    # singleton — no per-request state
_REDACTOR = ContextRedactor()      # stateless — safe to share


def governance_node(state: AgentState) -> AgentState:
    """
    Mandatory LangGraph node — Governance Gate.

    Position: after compression node, before model routing node.

    Steps:
    1. Run SecretPIIDetector.scan_context() over ranked_context.
    2. If scan times out → set governance_blocked=True; return state with empty
       ranked_context (fail-safe: no unscanned content reaches the LLM).
    3. Run ContextRedactor.redact_context() for critical/high findings.
    4. Record all findings in execution_trace (AC-7).
    5. Emit OTel span and Langfuse event.
    6. Return updated AgentState with redacted context and governance metadata.

    Note: this node is synchronous. SecretPIIDetector and ContextRedactor
    contain no I/O — regex scanning is CPU-bound and completes in < 200 ms.
    LangGraph supports sync nodes; wrapping in asyncio.to_thread is not required
    for a < 200 ms CPU operation.
    """
    ranked_context: list[dict] = state.get("ranked_context") or []

    with tracer.start_as_current_span("governance.scan") as span:
        span.set_attribute("governance.chunks_count", len(ranked_context))

        # ---- 1. Scan ----
        try:
            scan_result = _DETECTOR.scan_context(ranked_context)
        except GovernanceScanTimeoutError as exc:
            logger.error(
                "governance_node: scan timeout — blocking context from LLM. error=%s", exc
            )
            span.set_attribute("governance.blocked",    True)
            span.set_attribute("governance.timeout",    True)
            _record_trace(state, findings=[], scan_ms=0.0, blocked=True)
            return {
                **state,
                "ranked_context":      [],    # fail-safe: empty context, not unscanned content
                "governance_findings": [],
                "context_redacted":    False,
                "governance_scan_ms":  0.0,
                "governance_blocked":  True,
            }

        findings    = scan_result.findings
        scan_ms     = scan_result.scan_duration_ms
        span.set_attribute("governance.findings_count",       len(findings))
        span.set_attribute("governance.has_critical_or_high", scan_result.has_critical_or_high)
        span.set_attribute("governance.scan_ms",              scan_ms)

        # ---- 2. Redact critical/high findings ----
        if scan_result.has_critical_or_high:
            updated_context, _ = _REDACTOR.redact_context(ranked_context, scan_result)
            context_redacted   = True
        else:
            updated_context  = ranked_context
            context_redacted = False

        # ---- 3. Record in execution trace (AC-7) ----
        _record_trace(state, findings=findings, scan_ms=scan_ms, blocked=False)

        # ---- 4. Langfuse event ----
        langfuse.create_event(
            name   = "governance_scan",
            input  = {"chunks_scanned": scan_result.chunks_scanned},
            output = {
                "findings_count": len(findings),
                "redacted":       context_redacted,
                "scan_ms":        scan_ms,
            },
            metadata = {
                "critical_or_high": scan_result.has_critical_or_high,
                "pattern_types":    list({f.pattern_type.value for f in findings}),
            },
        )

        if findings:
            logger.warning(
                "governance_node: %d finding(s) detected, redacted=%s. "
                "Types: %s",
                len(findings),
                context_redacted,
                {f.pattern_type.value for f in findings},
            )

        return {
            **state,
            "ranked_context":      updated_context,
            "governance_findings": findings,
            "context_redacted":    context_redacted,
            "governance_scan_ms":  scan_ms,
            "governance_blocked":  False,
        }


def _record_trace(
    state:    AgentState,
    findings: list,
    scan_ms:  float,
    blocked:  bool,
) -> None:
    """
    Append governance findings to the execution_trace list (AC-7).
    execution_trace is a mutable list stored in AgentState. If absent, it is
    initialised here. The trace entry is dict-serialisable for downstream
    audit storage (EP-011).
    """
    trace_entry = {
        "node":       "governance",
        "scan_ms":    scan_ms,
        "blocked":    blocked,
        "findings":   [
            {
                "pattern_type": f.pattern_type.value,
                "severity":     f.severity.value,
                "chunk_id":     f.chunk_id,
                "char_offset":  f.char_offset,
                "preview":      f.match_preview,
            }
            for f in findings
        ],
    }
    existing_trace: list = state.get("execution_trace") or []
    # State is immutable in LangGraph between nodes; the returned state dict
    # carries the updated trace. We do not mutate `existing_trace` in place.
    state_ref = state  # type: ignore[assignment]
    # The caller (governance_node) reads the returned dict; this function
    # mutates `state_ref` directly only when called internally before the
    # return dict is constructed. Safe because governance_node returns a new dict.
    if "execution_trace" not in state or state["execution_trace"] is None:
        state_ref["execution_trace"] = [trace_entry]
    else:
        state_ref["execution_trace"] = existing_trace + [trace_entry]
```

---

### `StateGraph` registration (mandatory node)

```python
# src/agents/graph.py — extend existing StateGraph (do NOT replace)
from src.governance.nodes.governance_node import governance_node

# governance_node is mandatory — placed between compression and routing (AC-1).
# The existing edge from compression_node → routing_node is replaced by two edges.
graph.add_node("governance", governance_node)

# Remove existing direct edge: compression → routing
# (Exact edge name depends on US-017 implementation; adjust accordingly)
graph.add_edge("compression",  "governance")
graph.add_edge("governance",   "routing")
```

**Mandatory placement (AC-1):**

The node is registered in the `StateGraph` with no conditional routing — it is not wrapped in a `should_run` guard. Every invocation of the agent pipeline passes through `governance_node`. The only way the governance check is bypassed is if the context is empty before the node runs (in which case there is nothing to scan and the node returns immediately with empty findings).

**Synchronous vs async (performance):**

`governance_node()` is synchronous. LangGraph supports both sync and async nodes. `SecretPIIDetector.scan_context()` is CPU-bound regex (no I/O), and its budget is ≤ 200 ms — well within LangGraph's per-node execution window. Converting to `asyncio.to_thread` for a sub-200 ms CPU task would add thread-pool overhead without benefit.

## Acceptance Criteria

- [ ] `governance_node` is registered in the `StateGraph` with no conditional routing guard
- [ ] On a clean context (no findings), `governance_findings=[]`, `context_redacted=False`, `governance_blocked=False`
- [ ] On a context with a critical finding, `context_redacted=True` and `ranked_context` items have `[REDACTED:...]` substitutions
- [ ] On a medium-only finding, `context_redacted=False` — medium findings are not redacted
- [ ] `GovernanceScanTimeoutError` sets `governance_blocked=True` and returns `ranked_context=[]`
- [ ] `execution_trace` list contains a `"governance"` entry after the node runs (AC-7)
- [ ] OTel span `governance.scan` is created for every invocation
- [ ] `governance_scan_ms` in returned state matches `GovernanceScanResult.scan_duration_ms`

## Dependencies

- TASK-US031-01 (`DetectionFinding`, `GovernanceScanResult`)
- TASK-US031-02 (`PatternRegistry`)
- TASK-US031-03 (`SecretPIIDetector`, `GovernanceScanTimeoutError`, `ContextRedactor`)
- US-017 (compression node — `governance_node` is placed immediately after it)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests use `MagicMock` for OTel tracer and Langfuse; `SecretPIIDetector` and `ContextRedactor` are exercised directly (not mocked)
- [ ] `mypy --strict` passes; no `ruff` lint errors
