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

from src.agents.config import INTENT_CONFIDENCE_THRESHOLD, settings  # noqa: F401 — re-export for callers
from src.agents.schemas.clarification import ClarificationQuestion
from src.agents.state import AgentState, ExecutionStatus
from src.llm.local_ollama_chain import LiteLLMChain

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
        _clar_chain = (
            LiteLLMChain(
                _clar_prompt,
                StrOutputParser(),
                model_id=settings.llm_model_id,
                temperature=0.3,
                max_tokens=80,
                timeout_s=settings.llm_timeout_s,
            )
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

    try:
        chain = _get_clar_chain()
        raw_question = await chain.ainvoke({  # type: ignore[union-attr]
            "intent_type": intent,
            "confidence": confidence,
            "user_prompt": state["prompt"],
        })
        response_type = "clarification_needed"
    except Exception:
        raw_question = _fallback_question(intent)
        response_type = "clarification"

    guarded = _enforce_word_limit(raw_question.strip())
    question = ClarificationQuestion(question=guarded)
    confidence_pct = f"{confidence:.0%}"
    message = (
        f"Intent '{intent}' is only classified with {confidence_pct} confidence. "
        f"{question.question}"
    )

    return {
        "requires_clarification": True,
        "clarification_question": question.question,
        "status": ExecutionStatus.COMPLETE,
        "final_response": {
            "type": response_type,
            "question": question.question,
            "message": message,
            "original_prompt": state["prompt"],
            "session_id": state["request_id"],
            "clarification_round": state.get("clarification_round", 0),
        },
    }


def _fallback_question(intent: str) -> str:
    intent_label = str(intent or "unknown")
    return f"Which {intent_label} component or service do you want me to focus on?"
