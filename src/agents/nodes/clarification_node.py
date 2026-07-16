"""Clarification terminal node — TASK-US009-04 / TASK-US011-01.

Invoked when ``intent_confidence`` is below ``INTENT_CONFIDENCE_THRESHOLD``.
Generates a targeted LLM clarification question and sets ``requires_clarification``
so downstream consumers and audit replays can distinguish this exit from a
successful completion.

The LLM chain is a lazy module-level singleton (built on first invocation) so
the OpenAI client is never instantiated at import time — no API key required
during test collection.
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.agents.config import INTENT_CONFIDENCE_THRESHOLD  # noqa: F401 — re-export for callers
from src.agents.schemas.clarification import ClarificationQuestion
from src.agents.state import AgentState, ExecutionStatus

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

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

_clar_prompt = ChatPromptTemplate.from_messages([
    ("system", CLARIFICATION_SYSTEM_PROMPT),
    ("human", "Developer prompt: {user_prompt}"),
])

# Lazy singleton — built on first invocation to avoid API key validation at
# import time.  Tests replace this module attribute via unittest.mock.patch.
_clar_chain: object = None


def _get_clar_chain() -> object:
    """Return the module-level chain singleton, building it on first call."""
    global _clar_chain
    if _clar_chain is None:
        from langchain_openai import ChatOpenAI  # noqa: PLC0415

        _clar_chain = (
            _clar_prompt
            | ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=80)
            | StrOutputParser()
        )
    return _clar_chain


# ---------------------------------------------------------------------------
# Word-count guard
# ---------------------------------------------------------------------------

def _enforce_word_limit(text: str, limit: int = 50) -> str:
    """Truncate *text* to *limit* words, ensuring the result ends with ``?``."""
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(",;") + "?"


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


async def clarification_node(state: AgentState) -> dict:
    """Generate a targeted clarification question for low-confidence intent detection.

    Replaces the static template string with an LLM-generated question that is
    specific to the user's ambiguous prompt.  Sets ``requires_clarification = True``
    and ``status = COMPLETE`` so the pipeline terminates cleanly.

    Args:
        state: Current pipeline execution state.  Must contain
               ``intent_confidence`` (float), ``prompt`` (str), and
               optionally ``intent_type``.

    Returns:
        Partial state dict merged by LangGraph into the full ``AgentState``.
    """
    confidence: float = state["intent_confidence"]  # type: ignore[assignment]
    intent = state.get("intent_type") or "unknown"

    chain = _get_clar_chain()
    raw_question = await chain.ainvoke({  # type: ignore[union-attr]
        "intent_type": intent,
        "confidence": confidence,
        "user_prompt": state["prompt"],
    })

    guarded = _enforce_word_limit(raw_question.strip())
    question = ClarificationQuestion(question=guarded)

    return {
        "requires_clarification": True,
        "clarification_question": question.question,
        "status": ExecutionStatus.COMPLETE,
        "final_response": {
            "type": "clarification_needed",
            "question": question.question,
            "original_prompt": state["prompt"],
            "session_id": state["request_id"],
            "clarification_round": state.get("clarification_round", 0),
        },
    }
