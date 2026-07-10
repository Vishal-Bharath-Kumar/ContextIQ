# TASK-US009-01 — Implement Intent Classifier Node with LLM Prompt Chain

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US009-01 |
| User Story | US-009 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend / AI |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement the `intent_node()` LangGraph node that classifies an incoming developer prompt into one of the eight canonical intent types using a structured LLM chain. The node must complete classification within 500 ms for prompts up to 2 000 tokens and write its result into `AgentState`.

## Implementation Details

**Technology:** Python 3.11+, `langgraph>=0.2.0`, `langchain-openai`, `pydantic>=2.0`

**File locations:**
- `src/agents/nodes/intent_node.py` — node implementation and prompt template
- `src/agents/schemas/intent.py` — `IntentResult` Pydantic model
- `tests/agents/nodes/test_intent_node.py`

**Intent types (canonical enum):**

```python
# src/agents/schemas/intent.py
from enum import StrEnum

class IntentType(StrEnum):
    DEBUGGING      = "debugging"
    CODE_GEN       = "code-gen"
    ARCHITECTURE   = "architecture"
    DOCS           = "docs"
    INCIDENT       = "incident"
    METRICS        = "metrics"
    CODE_REVIEW    = "code-review"
    GENERAL        = "general"

class IntentResult(BaseModel):
    intent_type:   IntentType
    confidence:    float = Field(ge=0.0, le=1.0)
    reasoning:     str
```

**Classifier prompt template:**

```python
SYSTEM_PROMPT = """\
You are a developer-prompt intent classifier for an AI coding assistant.
Classify the prompt into exactly one of these intent types:
  debugging, code-gen, architecture, docs, incident, metrics, code-review, general

Respond ONLY with valid JSON matching the schema:
{"intent_type": "<type>", "confidence": <0.0–1.0>, "reasoning": "<one sentence>"}
"""
```

**Node implementation:**

```python
# src/agents/nodes/intent_node.py
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from src.agents.schemas.intent import IntentResult

_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human",  "{prompt_text}"),
])

_llm    = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_tokens=128)
_chain  = _prompt | _llm | JsonOutputParser()

async def intent_node(state: AgentState) -> dict:
    raw    = await _chain.ainvoke({"prompt_text": state["user_prompt"]})
    result = IntentResult.model_validate(raw)
    return {
        "intent_type":       result.intent_type,
        "intent_confidence": result.confidence,
    }
```

**Performance constraints:**
- `max_tokens=128` keeps LLM response minimal and within the 500 ms budget
- `gpt-4o-mini` p95 latency for ≤ 2 000 input tokens is ≈ 250 ms (empirically validated in AIR-005)
- Chain must be module-level singleton — do NOT re-instantiate the LLM per call

## Acceptance Criteria

- [ ] `intent_node()` correctly classifies a debugging prompt as `IntentType.DEBUGGING`
- [ ] `intent_node()` correctly classifies a "how do I set up X" prompt as `IntentType.DOCS`
- [ ] `IntentResult` raises `ValidationError` when `confidence` is outside `[0, 1]`
- [ ] Node returns a dict containing exactly `intent_type` and `intent_confidence` keys
- [ ] Classification completes within 500 ms for a 2 000-token prompt in the CI benchmark (mocked LLM latency ≤ 250 ms)
- [ ] All 8 intent types are reachable via the classifier (unit tests cover each type)

## Dependencies

- TASK-US005-01 (`AgentState` TypedDict — `intent_type` and `intent_confidence` fields added in TASK-US009-02)
- TASK-US006-01 (node registered as `"intent_agent"` in `build_graph()`)
- AIR-005 (model selection and prompt engineering spec)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Unit test coverage ≥ 85% for `src/agents/nodes/intent_node.py`
- [ ] All 8 intent types covered by parameterised unit tests
- [ ] `mypy --strict` passes; no `ruff` lint errors
- [ ] LLM call is mocked in tests — no live API calls in CI
