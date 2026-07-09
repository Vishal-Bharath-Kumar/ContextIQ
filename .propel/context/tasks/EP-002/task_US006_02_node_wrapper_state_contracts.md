# TASK-US006-02 — Node Wrapper for Typed State Pass-Through and Update Contracts

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US006-02 |
| User Story | US-006 |
| Epic | EP-002 — Supervisor Agent & Multi-Agent Pipeline |
| Layer | Backend |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Define a `NodeWrapper` that enforces the LangGraph node contract: each node receives the full `AgentState`, may only update its declared output fields, and must return a partial state dict. Includes a `@node_contract` decorator that validates output fields at runtime in non-production environments, preventing accidental state field overwrites between nodes.

## Implementation Details

**Technology:** Python 3.11+, `langgraph`, `pydantic`

**File locations:**
- `src/agents/nodes/base.py` — `NodeWrapper`, `@node_contract` decorator, `NodeOutputContract`
- `src/agents/nodes/contracts.py` — per-node output field declarations
- `tests/agents/test_node_contracts.py`

**LangGraph state update model:**
In LangGraph, a node returns a **partial dict** — only the fields it updates. LangGraph merges this into the current full state. Nodes must never return the full state or accidentally reset fields they don't own.

**`NodeOutputContract` — per-node allowed output fields:**
```python
# contracts.py
NODE_OUTPUT_CONTRACTS: dict[str, set[str]] = {
    "intent_agent": {
        "intent_type", "intent_confidence", "execution_plan",
        "status", "current_node", "error",
    },
    "retrieval_agent": {
        "raw_context", "ranked_context",
        "status", "current_node", "error",
    },
    "governance_agent": {
        "governance_decisions", "redacted_chunks", "ranked_context",
        "status", "current_node", "error",
    },
    "compression_agent": {
        "compressed_context", "tokens_before_compression", "tokens_after_compression",
        "status", "current_node", "error",
    },
    "routing_agent": {
        "selected_model", "model_routing_score", "final_response",
        "status", "current_node", "error",
    },
}
```

**`@node_contract` decorator (enforced in `DEBUG` mode only — zero overhead in production):**
```python
def node_contract(node_name: str):
    allowed = NODE_OUTPUT_CONTRACTS[node_name]

    def decorator(fn: Callable[[AgentState], Awaitable[dict]]):
        @functools.wraps(fn)
        async def wrapper(state: AgentState) -> dict:
            result = await fn(state)
            if settings.debug:
                unexpected = set(result.keys()) - allowed - {"status", "current_node", "error"}
                if unexpected:
                    raise ContractViolationError(
                        f"Node '{node_name}' wrote unexpected fields: {unexpected}. "
                        f"Allowed: {allowed}"
                    )
            return result
        return wrapper
    return decorator
```

**`NodeWrapper` combining contract + events + logging (composes TASK-US005-04 and TASK-US006-03):**
```python
def wrap(node_fn: Callable, node_name: str, publisher: StateEventPublisher) -> Callable:
    contracted = node_contract(node_name)(node_fn)
    logged     = with_node_logging(contracted, node_name)     # TASK-US006-03
    evented    = with_state_events(logged, node_name, publisher)  # TASK-US005-04
    return evented
```

**Immutable identity fields:** `request_id`, `user_id`, `prompt`, `timestamp`, `tool_name` are never in any node's `allowed` set — no node can overwrite them.

**`current_node` update:** Every node must set `current_node = node_name` in its return dict. The wrapper enforces this:
```python
if "current_node" not in result:
    result["current_node"] = node_name
```

## Acceptance Criteria

- [ ] A node returning a field outside its contract raises `ContractViolationError` in `DEBUG=true` mode
- [ ] The same node returns successfully in `DEBUG=false` mode (zero enforcement overhead)
- [ ] A node that forgets to set `current_node` has it added automatically by the wrapper
- [ ] Identity fields (`request_id`, `user_id`, `prompt`) are not in any node's allowed set
- [ ] Wrapper composition order is: contract check → logging → event publish (outermost)
- [ ] Unit tests cover: valid output, contract violation, missing `current_node`, identity field write attempt

## Dependencies

- TASK-US005-01 (`AgentState` with all field names)
- TASK-US005-04 (`with_state_events` wrapper composed here)
- TASK-US006-03 (`with_node_logging` wrapper composed here)

## Definition of Done

- [ ] `NodeOutputContract` covers all 5 pipeline nodes; reviewed and approved by tech lead
- [ ] Contract violations surface in local dev as clear error messages with field names
- [ ] `mypy --strict` passes on `nodes/base.py` and `nodes/contracts.py`
- [ ] `DEBUG` flag wired to `settings.debug` (set by `APP_ENV=development` env var)
