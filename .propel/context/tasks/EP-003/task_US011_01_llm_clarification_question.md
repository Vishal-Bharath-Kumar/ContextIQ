# TASK-US011-01 — LLM-Generated Targeted Clarification Question

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US011-01 |
| User Story | US-011 |
| Epic | EP-003 — Intent Detection & Context Planning |
| Layer | Backend / AI |
| Priority | P1 |
| Points | 2 |
| Status | Draft |

## Description

Replace the template-string message in `clarification_node` (TASK-US009-04) with an LLM chain that generates a targeted, concise clarification question (≤ 50 words) specific to the user's ambiguous prompt. The question must be singular, open-ended, and directly actionable so the user's reply moves confidence above the threshold.

## Implementation Details

**Technology:** Python 3.11+, `langchain-openai`, `langchain-core`, `pydantic>=2.0`

**File locations:**
- `src/agents/nodes/clarification_node.py` — replaces template string with LLM chain (extends TASK-US009-04)
- `src/agents/schemas/clarification.py` — `ClarificationQuestion` Pydantic model
- `tests/agents/nodes/test_clarification_node.py`

**`ClarificationQuestion` model:**

```python
# src/agents/schemas/clarification.py
from pydantic import BaseModel, Field

class ClarificationQuestion(BaseModel):
    question: str = Field(
        description="One focused question ≤ 50 words that resolves prompt ambiguity.",
        max_length=300,          # hard cap on raw string length as a secondary guard
    )
```

**Clarification generation prompt:**

```python
CLARIFICATION_SYSTEM_PROMPT = """\
You are an AI assistant helping a software developer clarify an ambiguous request.
The developer's prompt was classified as intent '{intent_type}' with only {confidence:.0%} confidence.

Write ONE concise, specific clarifying question (≤ 50 words) that will help determine:
- What the developer is actually trying to accomplish
- Which technology, service, or component they are referring to

Rules:
- Ask exactly one question — no compound questions
- Do not repeat or paraphrase the original prompt
- Do not apologise or explain your reasoning
Respond with ONLY the question text, no punctuation other than the question mark.
"""
```

**Updated `clarification_node()`:**

```python
# src/agents/nodes/clarification_node.py
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from src.agents.schemas.clarification import ClarificationQuestion

_clar_prompt = ChatPromptTemplate.from_messages([
    ("system", CLARIFICATION_SYSTEM_PROMPT),
    ("human",  "Developer prompt: {user_prompt}"),
])
_clar_llm   = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=80)
_clar_chain = _clar_prompt | _clar_llm | StrOutputParser()

async def clarification_node(state: AgentState) -> dict:
    confidence = state["intent_confidence"]
    intent     = state.get("intent_type", "unknown")

    raw_question = await _clar_chain.ainvoke({
        "intent_type":  intent,
        "confidence":   confidence,
        "user_prompt":  state["prompt"],
    })

    question = ClarificationQuestion(question=raw_question.strip())

    return {
        "requires_clarification": True,
        "clarification_question": question.question,
        "status": ExecutionStatus.COMPLETE,
    }
```

**`AgentState` additions (extend `src/agents/state.py`):**

```python
clarification_question: Optional[str]   # the generated question text
```

**Word-count guard:** A post-generation validator counts words and truncates at sentence boundary if the LLM exceeds 50 words. This is a defensive measure only — `gpt-4o-mini` at `max_tokens=80` cannot physically generate a response longer than the limit.

```python
def _enforce_word_limit(text: str, limit: int = 50) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(",;") + "?"
```

## Acceptance Criteria

- [ ] `clarification_node()` generates a question rather than a template string
- [ ] Generated question contains no more than 50 words
- [ ] Generated question is a single interrogative sentence ending in `?`
- [ ] `clarification_question` field is populated in `AgentState` after the node runs
- [ ] `_enforce_word_limit()` truncates at 50 words and ensures the result ends with `?`
- [ ] LLM call is mocked in tests — no live API calls in CI

## Dependencies

- TASK-US009-04 (`clarification_node` skeleton and `requires_clarification` state flag)
- TASK-US009-02 (`AgentState` — `clarification_question` field added here)
- TASK-US011-02 (MCP response formatter reads `clarification_question`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Template string removed from `clarification_node` — no hardcoded question text remains
- [ ] Unit tests assert: question ≤ 50 words, ends with `?`, `clarification_question` in state patch
- [ ] `_clar_chain` is a module-level singleton — not re-instantiated per call
- [ ] `mypy --strict` passes; no `ruff` lint errors
