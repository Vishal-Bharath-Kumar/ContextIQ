"""LLM-based entity-preserving summarisation chain (TASK-US017-03 / AIR-015)."""

from __future__ import annotations

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.compression.summarization.settings import get_summarization_settings
from src.llm.local_ollama_chain import LiteLLMChain

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


class SummarizationOutput(BaseModel):
    summary: str = Field(description="Compressed summary of the source chunk.")
    retained_entities: list[str] = Field(
        description="Named entities, code identifiers, error codes, and action items preserved.",
        default_factory=list,
    )


class SummarizationChain:
    """Async LangChain chain that summarises a single chunk to ≤ 40% of its original token count."""

    def __init__(self) -> None:
        settings = get_summarization_settings()
        self._settings = settings
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SUMMARIZATION_SYSTEM_PROMPT),
            ("human", "Source chunk (approx. {input_tokens} tokens):\n\n{content}"),
        ])
        self._chain = LiteLLMChain(
            self._prompt,
            JsonOutputParser(),
            model_id=settings.model_name,
            temperature=0.0,
            max_tokens=settings.max_output_tokens,
            timeout_s=settings.timeout_s,
        )

    async def summarise(
        self,
        content: str,
        input_tokens: int,
        callbacks: list | None = None,
    ) -> SummarizationOutput:
        """Summarise a single chunk and validate the output schema.

        Args:
            content: Raw chunk text.
            input_tokens: Pre-computed token count for the prompt.
            callbacks: Optional LangChain callbacks (e.g. Langfuse handler).
        """
        target_pct = int(self._settings.target_ratio * 100)
        raw = await self._chain.ainvoke(
            {"content": content, "input_tokens": input_tokens, "target_pct": target_pct},
            config={"callbacks": callbacks or []},
        )
        return SummarizationOutput.model_validate(raw)
