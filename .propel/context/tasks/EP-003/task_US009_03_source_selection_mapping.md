# TASK-US009-03 — Implement Intent-to-Source-Selection Mapping (AIR-006)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US009-03 |
| User Story | US-009 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend / AI |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the source-selection mapper that translates an intent type into an ordered list of knowledge-source keys. This is the runtime implementation of the AIR-006 source-selection mapping spec. The mapper runs immediately after `intent_node()` and writes `intent_source_list` into `AgentState` so the Retrieval Agent can query only the relevant connectors.

## Implementation Details

**Technology:** Python 3.11+

**File locations:**
- `src/agents/source_selector.py` — `SOURCE_MAP` constant and `select_sources()` function
- `tests/agents/test_source_selector.py`

**Source map (AIR-006 canonical mapping):**

```python
# src/agents/source_selector.py
from src.agents.schemas.intent import IntentType

SOURCE_MAP: dict[IntentType, list[str]] = {
    IntentType.DEBUGGING:    ["github", "stackoverflow", "jira"],
    IntentType.CODE_GEN:     ["github", "confluence"],
    IntentType.ARCHITECTURE: ["confluence", "github", "miro"],
    IntentType.DOCS:         ["confluence", "github"],
    IntentType.INCIDENT:     ["grafana", "jira", "pagerduty"],
    IntentType.METRICS:      ["grafana", "datadog"],
    IntentType.CODE_REVIEW:  ["github"],
    IntentType.GENERAL:      ["confluence", "github", "stackoverflow"],
}

FALLBACK_SOURCES: list[str] = [
    "github", "confluence", "grafana", "jira",
    "stackoverflow", "miro", "pagerduty", "datadog",
]

def select_sources(intent_type: IntentType, confidence: float) -> list[str]:
    """Return ordered source keys for the given intent.

    Falls back to all sources when confidence < 0.6 (US-009 AC-5).
    """
    if confidence < 0.6:
        return FALLBACK_SOURCES
    return SOURCE_MAP[intent_type]
```

**Integration into `intent_node()`:**

Call `select_sources()` at the end of `intent_node()` and include `intent_source_list` in the returned state patch:

```python
# src/agents/nodes/intent_node.py  (extend TASK-US009-01 output)
from src.agents.source_selector import select_sources

async def intent_node(state: AgentState) -> dict:
    raw    = await _chain.ainvoke({"prompt_text": state["user_prompt"]})
    result = IntentResult.model_validate(raw)
    return {
        "intent_type":        result.intent_type,
        "intent_confidence":  result.confidence,
        "intent_source_list": select_sources(result.intent_type, result.confidence),
    }
```

**Source key registry:**
- Source keys are lowercase strings matching connector IDs registered in the Connector Registry (EP-002, TASK-US007-04)
- Keys in `SOURCE_MAP` must be a strict subset of registered connector IDs; a startup assertion validates this

```python
# src/agents/source_selector.py — startup guard
def _validate_source_map(registered_ids: set[str]) -> None:
    all_mapped = {s for sources in SOURCE_MAP.values() for s in sources}
    unknown = all_mapped - registered_ids
    if unknown:
        raise ValueError(f"SOURCE_MAP references unregistered connectors: {unknown}")
```

## Acceptance Criteria

- [ ] `select_sources(IntentType.INCIDENT, 0.9)` returns `["grafana", "jira", "pagerduty"]`
- [ ] `select_sources(IntentType.CODE_GEN, 0.4)` returns `FALLBACK_SOURCES` (confidence < 0.6)
- [ ] All 8 intent types are present as keys in `SOURCE_MAP`
- [ ] `intent_node()` state patch includes `intent_source_list` after this task is applied
- [ ] `_validate_source_map()` raises `ValueError` when given a set that omits a mapped connector
- [ ] Unit tests cover: each intent type's expected sources, fallback trigger at confidence boundary

## Dependencies

- TASK-US009-01 (`intent_node()` — returns the state patch that includes `intent_source_list`)
- TASK-US009-02 (`AgentState.intent_source_list` field)
- TASK-US007-04 (Connector Registry — source keys must match registered connector IDs)
- AIR-006 (source-selection mapping specification)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `SOURCE_MAP` covers all 8 intent types with no duplicate keys
- [ ] Unit test coverage ≥ 85% for `src/agents/source_selector.py`
- [ ] Startup validation guard is invoked in the FastAPI lifespan hook
- [ ] `mypy --strict` passes; no `ruff` lint errors
