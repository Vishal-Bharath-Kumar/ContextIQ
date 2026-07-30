"""Intent classifier node — EP-003 implementation.

Classifies an incoming developer prompt into one of eight canonical intent
types via a structured LLM chain.  The chain is a lazy module-level singleton
(built on first invocation) so the LLM client is never re-instantiated per
call and no API key is required at import time.

Performance contract: completes within 500 ms for prompts up to 2 000 tokens
(``max_tokens=128`` keeps the response minimal; local Ollama is expected).

OTel instrumentation (TASK-US009-05): every execution emits an
``intent_agent.classify`` span with attributes ``intent.type``,
``intent.confidence``, ``intent.latency_ms``, and ``intent.low_confidence``.
"""

from __future__ import annotations

import time

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from opentelemetry import trace

from src.agents.config import INTENT_CONFIDENCE_THRESHOLD, MAX_CLARIFICATION_ROUNDS
from src.agents.planning.plan_generator import generate_execution_plan
from src.agents.schemas.intent import IntentResult
from src.agents.source_selector import select_sources
from src.agents.state import AgentState, ExecutionStatus
from src.llm.local_ollama_chain import LiteLLMChain
from src.observability.tracing.node_span import otel_node_span

_tracer = trace.get_tracer("contextiq.intent_agent")

SYSTEM_PROMPT = """\
You are a developer-prompt intent classifier for an AI coding assistant.
Classify the prompt into exactly one of these intent types:
  debugging, code-gen, architecture, docs, incident, metrics, code-review, general

Respond ONLY with valid JSON matching the schema:
{"intent_type": "<type>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}
"""

_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "{prompt_text}"),
])

# Lazy singleton — built on first invocation to avoid API key validation at
# import time.  Tests replace this module attribute via unittest.mock.patch.
_chain: object = None


def _get_chain() -> object:
    """Return the module-level chain singleton, building it on first call."""
    global _chain
    if _chain is None:
        _chain = (
            LiteLLMChain(
                _prompt,
                JsonOutputParser(),
                model_id=settings.llm_model_id,
                temperature=0.0,
                max_tokens=128,
                timeout_s=settings.llm_timeout_s,
            )
        )
    return _chain


@otel_node_span("intent.classify")
async def intent_node(state: AgentState) -> dict:
    """LangGraph node that classifies the user prompt and updates AgentState.

    Reads ``state["prompt"]``, invokes the LLM classification chain, and
    returns a partial state dict containing only the fields this node owns.

    Emits an ``intent_agent.classify`` OTel span with attributes:
    ``intent.type``, ``intent.confidence``, ``intent.latency_ms``, and
    ``intent.low_confidence`` (TASK-US009-05).

    Returns:
        dict with keys ``intent_type``, ``intent_confidence``,
        ``intent_source_list``, ``current_node``, and ``status``.
    """
    with _tracer.start_as_current_span("intent_agent.classify") as span:
        t0 = time.perf_counter()
        raw = await _get_chain().ainvoke({"prompt_text": state["prompt"]})
        result = IntentResult.model_validate(raw)
        sources = select_sources(result.intent_type, result.confidence)
        plan = generate_execution_plan(result.intent_type, result.confidence, sources)
        latency_ms = (time.perf_counter() - t0) * 1000

        span.set_attributes({
            "intent.type": result.intent_type,
            "intent.confidence": result.confidence,
            "intent.latency_ms": round(latency_ms, 2),
            "intent.low_confidence": result.confidence < INTENT_CONFIDENCE_THRESHOLD,
            "intent.plan.sources": ",".join(plan.sources),
            "intent.plan.strategy": plan.ranking_strategy,
            "intent.plan.cache": plan.cache_eligible,
            "intent.cap_forced_retrieval": (
                result.confidence < INTENT_CONFIDENCE_THRESHOLD
                and state.get("clarification_round", 0) >= MAX_CLARIFICATION_ROUNDS
            ),
        })

        return {
            "intent_type": result.intent_type,
            "intent_confidence": result.confidence,
            "intent_source_list": sources,
            "execution_plan": plan,
            "current_node": "intent_agent",
            "status": ExecutionStatus.RUNNING,
        }


