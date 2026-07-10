# TASK-US017-03 — Entity-Preserving Summarization LLM Chain (AIR-015)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US017-03 |
| User Story | US-017 |
| Epic | EP-005 — AI Compression Engine |
| Layer | Backend / AI |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Implement `SummarizationChain`, the LangChain async chain that summarises a single chunk to ≤ 40% of its original token count while preserving all named entities, code identifiers, error codes, and action items. The prompt is engineered against the AIR-015 quality spec. A structured `SummarizationOutput` Pydantic model validates the LLM response and enforces the completeness contract.

## Implementation Details

**Technology:** Python 3.11+, `langchain-openai`, `langchain-core`, `pydantic>=2.0`

**File locations:**
- `src/compression/summarization/chain.py` — `SummarizationChain` and `SummarizationOutput`
- `tests/compression/summarization/test_chain.py`

**`SummarizationOutput` model:**

```python
# src/compression/summarization/chain.py
from pydantic import BaseModel, Field

class SummarizationOutput(BaseModel):
    summary:          str  = Field(description="Compressed summary of the source chunk.")
    retained_entities: list[str] = Field(
        description="Named entities, code identifiers, error codes, and action items preserved.",
        default_factory=list,
    )
```

**Summarisation system prompt (AIR-015 canonical):**

```python
SUMMARIZATION_SYSTEM_PROMPT = """\
You are a technical documentation compressor for a software engineering AI assistant.
Your task: summarize the provided context chunk to roughly {target_pct}% of its original length.

MANDATORY preservation rules — these items MUST appear verbatim in the summary:
  • Named entities: service names, team names, person names
  • Code identifiers: function names, class names, variable names, API endpoints, config keys
  • Error codes and HTTP status codes: e.g. HTTP 401, ERR_CONN_REFUSED, ORA-00942
  • Action items and imperatives: steps, commands, instructions prefixed with verbs
  • Version numbers and SLAs

Format your response as JSON matching this schema:
{{"summary": "<compressed text>", "retained_entities": ["<entity1>", ...]}}

Rules:
  - Do not add information not present in the source
  - Do not use bullet points unless the source uses them
  - Write in the same technical register as the source (code comments, prose, etc.)
  - Never output partial JSON
"""
```

**`SummarizationChain`:**

```python
from langchain_openai          import ChatOpenAI
from langchain_core.prompts    import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from src.compression.summarization.settings import get_summarization_settings

class SummarizationChain:
    def __init__(self) -> None:
        settings = get_summarization_settings()
        self._settings = settings
        self._llm = ChatOpenAI(
            model      = settings.model_name,
            temperature = 0.0,              # deterministic output for reproducibility
            max_tokens  = settings.max_output_tokens,
        )
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SUMMARIZATION_SYSTEM_PROMPT),
            ("human",  "Source chunk (approx. {input_tokens} tokens):\n\n{content}"),
        ])
        self._chain = self._prompt | self._llm | JsonOutputParser()

    async def summarise(
        self,
        content:      str,
        input_tokens: int,
        callbacks:    list | None = None,
    ) -> SummarizationOutput:
        """Summarise a single chunk and validate the output schema.

        Args:
            content      — raw chunk text
            input_tokens — pre-computed token count for the prompt
            callbacks    — optional LangChain callbacks (e.g. Langfuse handler)
        """
        target_pct = int(self._settings.target_ratio * 100)
        raw = await self._chain.ainvoke(
            {"content": content, "input_tokens": input_tokens, "target_pct": target_pct},
            config={"callbacks": callbacks or []},
        )
        return SummarizationOutput.model_validate(raw)
```

**Prompt engineering rationale (AIR-015):**
- `temperature=0.0` ensures identical summaries for identical input, enabling cache-based deduplication of summarisation LLM calls in future
- `max_tokens=400` (from settings) enforces the output token cap without relying on the model's judgment
- Structured JSON output via `JsonOutputParser` ensures `SummarizationOutput` can always be validated; the fallback on parse failure is to return the original chunk unmodified (handled in TASK-US017-04)
- The `retained_entities` list is used by the eval harness (TASK-US017-04) to measure > 90% key-fact retention

## Acceptance Criteria

- [ ] `SummarizationChain.summarise()` returns a `SummarizationOutput` with a non-empty `summary`
- [ ] A chunk containing `"HTTP 401"` produces a summary where `"HTTP 401"` is present in `summary`
- [ ] A chunk containing `"def authenticate()"` produces a summary where `"authenticate"` appears in `summary` or `retained_entities`
- [ ] `SummarizationOutput.model_validate({"summary": "...", "retained_entities": []})` succeeds
- [ ] The LLM chain is constructed once at `SummarizationChain.__init__` — not per call
- [ ] All LLM calls are mocked in unit tests — no live API calls in CI

## Dependencies

- TASK-US017-02 (`SummarizationSettings` — `model_name`, `max_output_tokens`, `target_ratio`)
- TASK-US017-05 (Langfuse `CallbackHandler` passed as `callbacks` argument)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Prompt is stored as a module-level constant — no inline f-string prompt construction in `summarise()`
- [ ] `JsonOutputParser` used — no manual `json.loads()` calls on LLM output
- [ ] Unit tests cover: valid output, `retained_entities` extraction, JSON parse with mocked LLM
- [ ] `mypy --strict` passes; no `ruff` lint errors
