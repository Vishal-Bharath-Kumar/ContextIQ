# Workflow Refactoring Plan

## Purpose

This document turns the workflow analysis into a concrete refactoring plan.
The goal is not to redesign the platform from scratch. The goal is to reduce
runtime drift, make connector behavior consistent, and harden the async handoff
points that currently carry most of the operational risk.

## Related Documents

- [application-workflow.md](application-workflow.md) for the full system workflow
- [mcp-request-workflow.md](mcp-request-workflow.md) for the MCP request path
- [pipeline-topology.md](pipeline-topology.md) for the LangGraph topology

## Problem Statement

The current architecture works, but the same runtime dependencies are wired in
multiple places.

The main duplication points are:

1. graph initialization across `src/main.py`, `src/gateway/main.py`, and `src/agent_worker/main.py`
2. connector registry and source-specific connector construction across sync, retrieval, health check, and indexing paths
3. event contract handling across sync, indexing, and knowledge-graph consumers
4. overlapping execution topologies between in-process graph execution and agent-worker graph execution

This creates three practical risks:

1. one runtime can behave differently from another after a partial fix
2. a successful upstream stage can fail silently at an async event boundary
3. connector behavior can differ by call path even for the same knowledge source

## Refactoring Goals

1. Make graph runtime setup deterministic across all entrypoints.
2. Make source-scoped connector construction reusable and consistent.
3. Make async event contracts explicit, typed, and testable.
4. Preserve the current feature surface while reducing operational branching.
5. Improve observability at the boundaries where work changes process or transport.

## Non-Goals

1. Replacing LangGraph.
2. Replacing Kafka with synchronous processing.
3. Changing the user-facing knowledge-source or MCP APIs unless required for correctness.
4. Rebuilding the connector SDK from scratch.

## Target End State

The preferred end state is:

1. one shared runtime bootstrap module used by every process that hosts the graph
2. one canonical source-connector factory used by sync, retrieval, indexing, and health-check paths
3. one typed event layer for sync and indexing events, with producer-side builders and consumer-side contract tests
4. one clearly documented primary AI execution path, with secondary paths explicitly limited to fallback or local development scenarios

## Workstream 1: Consolidate Runtime Bootstrap

### Why

`src/main.py`, `src/gateway/main.py`, and `src/agent_worker/main.py` all build
nearly the same dependency stack: connector registry, routing runtime, OPA
client, trace-writer dependencies, graph checkpointer, and the compiled graph.

### Deliverables

1. Extract a shared bootstrap module that builds the graph runtime dependencies.
2. Return a structured runtime object instead of mutating app state inline.
3. Keep process-specific startup concerns outside the shared module.

### Candidate extraction surface

- connector registry load and runtime overrides
- routing runtime services
- trace object store and trace session factory
- OPA client and health initialization
- graph compilation and graph registration hooks

### Validation

1. parity tests proving all three entrypoints receive the same runtime components
2. smoke tests for `/healthz`, MCP graph access, and agent-worker `/v1/execute`

## Workstream 2: Normalize Source-Scoped Connector Construction

### Why

The startup registry is connector-type oriented, but several workflows need a
connector built from a single `knowledge_sources` row with its own Vault path
and scope. Today that logic is spread across multiple code paths.

### Deliverables

1. Introduce a shared source-connector factory service.
2. Make it the only place that maps connector type to config class and scope field.
3. Reuse it in sync, indexing, retrieval loader, and health-check code.

### Candidate call sites

- `src/knowledge_sources/sync/executor.py`
- `src/indexing/pipeline.py`
- `src/agents/retrieval/connector_loader.py`
- knowledge-source health-check service

### Validation

1. contract tests that one source row produces the same effective connector config regardless of caller
2. integration tests for GitHub-style source-specific Vault path and scope handling

## Workstream 3: Clarify the Canonical AI Execution Path

### Why

The platform currently supports both local graph execution and remote
agent-worker execution. That flexibility is useful, but it is also a drift
multiplier when behavior or dependencies are fixed in only one path.

### Deliverables

1. Choose and document one primary production execution path.
2. Explicitly classify the alternate path as either fallback, dev-only, or supported parity mode.
3. Add parity coverage for any behavior that must remain valid in both paths.

### Decision options

1. Gateway or API always dispatches graph execution to the agent worker.
2. In-process execution remains only for built-in fallback tools and local development.
3. If both remain first-class, add a dedicated parity test suite and shared bootstrap enforcement.

### Validation

1. one end-to-end test per supported execution path
2. explicit docs explaining when each path is expected to run

## Workstream 4: Harden Event Contracts and Async Boundaries

### Why

The sync, indexing, and graph-enrichment pipeline depends on Kafka payloads
matching consumer expectations exactly. Schema drift at these boundaries can
turn a visible success upstream into a silent no-op downstream.

### Deliverables

1. centralize event schema ownership by topic
2. add producer-side event builder functions instead of open-coded dict assembly
3. add contract tests that validate serialized producer payloads against consumer models
4. standardize correlation fields across all events

### Priority topics

- `knowledge.source.synced`
- `knowledge.chunk.indexed`
- `knowledge.document.deleted`
- `knowledge.graph.updated`

### Validation

1. round-trip serialization tests for each event type
2. consumer tests that reject malformed payloads with actionable logging

## Workstream 5: Improve Observability at Handoffs

### Why

The hardest failures in this system happen when work crosses a boundary:
gateway to worker, sync to Kafka, Kafka to indexing, and indexing to graph
enrichment.

### Deliverables

1. standardize logging keys for `request_id`, `job_id`, `source_id`, `tenant_id`, and `connector_type`
2. ensure trace propagation across gateway and agent worker remains mandatory on supported paths
3. add handoff-specific metrics for dropped events, schema failures, and empty-index results
4. document expected signals for each stage in one runbook

### Validation

1. trace inspection from gateway receipt through worker execution
2. metrics and log assertions in integration tests around event consumption

## Suggested Delivery Order

1. Consolidate runtime bootstrap.
2. Normalize source-scoped connector construction.
3. Harden event contracts.
4. Clarify the canonical AI execution path.
5. Expand observability and operational runbooks.

This order reduces the highest configuration drift first, then addresses the
data-plane boundaries that are most likely to fail silently.

## Exit Criteria

The refactoring should be considered complete only when all of the following
are true:

1. the API, gateway, and agent worker no longer duplicate graph dependency wiring by hand
2. the same knowledge source resolves to the same effective connector config in every workflow
3. event payloads are constructed through typed helpers and covered by contract tests
4. the primary execution topology is explicit in both code and docs
5. failures at process and transport handoffs emit enough logs and metrics to diagnose quickly