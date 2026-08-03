"""AI context engineering tools.

TASK-BRD-18: Implements MCP tools for AI context capabilities:
- generate_context: Generate optimized context for AI requests
- compress_context: Apply AI compression to reduce tokens
- replay_execution: Replay a previous AI execution
"""
from __future__ import annotations

from collections import Counter
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP
from src.agents.config import settings as agent_settings
from src.agents.state import ExecutionStatus
from src.gateway.context.request_context import get_request_context
from src.gateway.tools.enterprise._local_tools import (
    CODE_ROOTS,
    DOC_ROOT,
    build_error_response,
    build_tool_response,
    json_text_response,
    search_workspace,
    workspace_coverage,
)
from src.model_router.config import RoutingSettings
from src.retrieval.ranking.filters import count_tokens
from mcp.types import TextContent

logger = logging.getLogger(__name__)

_ROUTING_SETTINGS = RoutingSettings()


def register_context_tools(mcp: FastMCP, context_service: Any = None) -> None:
    """Register AI context tools on the MCP server.
    
    Parameters
    ----------
    mcp:
        FastMCP server instance
    context_service:
        Context orchestration service
    """

    @mcp.tool()
    async def generate_context(
        prompt: str,
        max_tokens: int = 4000,
        compression_level: str = "medium",
    ) -> list[TextContent]:
        """Generate optimized enterprise context for an AI request.
        
        Orchestrates the full context engineering pipeline: intent detection,
        retrieval, ranking, compression, and governance.
        
        Parameters
        ----------
        prompt:
            User's prompt or question
        max_tokens:
            Maximum context size in tokens
        compression_level:
            Compression aggressiveness (low, medium, high)
            
        Returns
        -------
        list[TextContent]:
            Optimized context package ready for LLM
        """
        try:
            started = time.perf_counter()
            result = await _generate_context_payload(
                prompt=prompt,
                max_tokens=max_tokens,
                compression_level=compression_level,
                context_service=context_service,
            )
            result.setdefault("diagnostics", {})["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            
            logger.info(
                "generate_context completed: tokens=%d, compression=%s, status=%s, adapter=%s",
                max_tokens,
                compression_level,
                result.get("status"),
                (result.get("diagnostics") or {}).get("adapter"),
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("generate_context failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Context generation failed before any response could be assembled.",
                    error=e,
                    diagnostics={"adapter": "generate_context"},
                )
            )

    @mcp.tool()
    async def compress_context(
        content: str,
        target_compression: float = 0.8,
    ) -> list[TextContent]:
        """Apply AI-powered compression to reduce token usage.
        
        Uses multi-stage compression: deduplication, semantic merging,
        and LLM-based summarization.
        
        Parameters
        ----------
        content:
            Content to compress
        target_compression:
            Target compression ratio (0.8 = 80% reduction)
            
        Returns
        -------
        list[TextContent]:
            Compressed content with metrics
        """
        try:
            paragraphs = [part.strip() for part in content.split("\n\n") if part.strip()]
            deduped: list[str] = []
            seen: set[str] = set()
            for paragraph in paragraphs:
                key = " ".join(paragraph.lower().split())
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(paragraph)

            original_length = len(content)
            target_length = max(int(original_length * (1 - target_compression)), 0)
            compressed_content = "\n\n".join(deduped)
            if target_length and len(compressed_content) > target_length:
                compressed_content = compressed_content[:target_length].rstrip()

            tokens_before = count_tokens(content)
            tokens_after = count_tokens(compressed_content)
            result = build_tool_response(
                status="success" if compressed_content else "empty",
                summary="Compressed the supplied content." if compressed_content else "No content remained after compression.",
                data={
                    "original_length": original_length,
                    "compressed_length": len(compressed_content),
                    "compressed_content": compressed_content,
                    "removed_items": max(len(paragraphs) - len(deduped), 0),
                },
                diagnostics={"adapter": "local_compressor"},
                compression={
                    "enabled": True,
                    "method": "paragraph_dedup_truncate",
                    "target_ratio": target_compression,
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                    "ratio": _compression_ratio(tokens_before, tokens_after),
                },
            )
            result.update(
                {
                    "original_length": original_length,
                    "compressed_length": len(compressed_content),
                    "compressed_content": compressed_content,
                    "removed_items": max(len(paragraphs) - len(deduped), 0),
                }
            )
            
            logger.info(
                "compress_context invoked: original=%d, target_ratio=%.2f",
                original_length,
                target_compression,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("compress_context failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Context compression failed.",
                    error=e,
                    diagnostics={"adapter": "local_compressor"},
                )
            )

    @mcp.tool()
    async def replay_execution(
        execution_id: str,
    ) -> list[TextContent]:
        """Replay a previous AI execution for debugging or analysis.
        
        Retrieves complete execution metadata including prompt, context,
        agent decisions, selected model, and response.
        
        Parameters
        ----------
        execution_id:
            Unique execution identifier
            
        Returns
        -------
        list[TextContent]:
            Full execution replay with timeline
        """
        try:
            result = await _replay_execution_payload(execution_id, context_service)
            
            logger.info("replay_execution invoked: execution_id=%s", execution_id)
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("replay_execution failed: %s", e, exc_info=True)
            return json_text_response(
                build_error_response(
                    summary="Execution replay failed.",
                    error=e,
                    diagnostics={"adapter": "trace_replay"},
                )
            )


async def _generate_context_payload(
    *,
    prompt: str,
    max_tokens: int,
    compression_level: str,
    context_service: Any = None,
) -> dict[str, Any]:
    if context_service is not None and hasattr(context_service, "generate_context"):
        service_payload = await context_service.generate_context(
            prompt,
            max_tokens=max_tokens,
            compression_level=compression_level,
        )
        return _normalise_context_payload(
            service_payload,
            prompt=prompt,
            max_tokens=max_tokens,
            compression_level=compression_level,
            adapter="context_service",
        )

    pipeline_result = await _try_pipeline_context(prompt)
    if pipeline_result is not None:
        normalised_pipeline = await _normalise_pipeline_context_payload(
            pipeline_result,
            prompt=prompt,
            max_tokens=max_tokens,
            compression_level=compression_level,
        )
        pipeline_data = normalised_pipeline.get("data") if isinstance(normalised_pipeline.get("data"), dict) else {}
        pipeline_context = (pipeline_data.get("context") or []) if isinstance(pipeline_data, dict) else []
        pipeline_answer = pipeline_data.get("answer") if isinstance(pipeline_data, dict) else None
        if not pipeline_context and not pipeline_answer:
            degraded_reasons = list(((normalised_pipeline.get("diagnostics") or {}).get("degraded_reasons") or []))
            degraded_reasons.append("LangGraph pipeline returned no usable context; workspace fallback retrieval was used.")
            return await _build_workspace_fallback_context_payload(
                prompt=prompt,
                max_tokens=max_tokens,
                compression_level=compression_level,
                degraded_reason="; ".join(str(reason) for reason in degraded_reasons if reason),
            )
        return normalised_pipeline

    return await _build_workspace_fallback_context_payload(
        prompt=prompt,
        max_tokens=max_tokens,
        compression_level=compression_level,
        degraded_reason="LangGraph pipeline unavailable or failed; used workspace-backed fallback retrieval.",
    )


async def _try_pipeline_context(prompt: str) -> dict[str, Any] | None:
    try:
        from src.gateway.tools.clarification_reply import get_graph  # noqa: PLC0415
    except Exception:
        logger.debug("generate_context pipeline unavailable: graph accessor import failed", exc_info=True)
        return None

    try:
        graph = get_graph()
    except Exception:
        logger.debug("generate_context pipeline unavailable: graph not initialised", exc_info=True)
        return None

    request_id = str(uuid.uuid4())
    user_id = "enterprise-tools"
    username = "enterprise-tools"
    roles = ["platform_engineer"]
    try:
        ctx = get_request_context()
    except LookupError:
        ctx = None
    if ctx is not None:
        user_id = ctx.user_id
        username = ctx.username or ctx.user_id
        roles = list(ctx.roles) or roles

    state = {
        "request_id": request_id,
        "user_id": user_id,
        "username": username,
        "roles": roles,
        "tool_name": "generate_context",
        "prompt": prompt,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": ExecutionStatus.PENDING,
        "current_node": "",
        "error": None,
        "intent_type": None,
        "intent_confidence": None,
        "intent_source_list": None,
        "execution_plan": None,
        "requires_clarification": None,
        "clarification_question": None,
        "clarification_round": 0,
        "raw_context": None,
        "ranked_context": None,
        "degraded_sources": None,
        "compressed_context": None,
        "tokens_before_compression": None,
        "tokens_after_compression": None,
        "governance_decisions": None,
        "redacted_chunks": None,
        "selected_model": None,
        "model_routing_score": None,
        "final_response": None,
    }
    try:
        result = await graph.ainvoke(state, config={"configurable": {"thread_id": request_id}})
    except Exception:
        logger.warning("generate_context pipeline invocation failed", exc_info=True)
        return None
    if result.get("status") == ExecutionStatus.FAILED:
        logger.warning(
            "generate_context pipeline returned failed state: %s",
            result.get("error"),
        )
        return None
    return result


async def _replay_execution_payload(execution_id: str, context_service: Any = None) -> dict[str, Any]:
    if context_service is not None and hasattr(context_service, "replay_execution"):
        result = await context_service.replay_execution(execution_id)
        return _normalise_replay_payload(result, execution_id, adapter="context_service")

    try:
        import uuid as _uuid

        import redis.asyncio as aioredis  # noqa: PLC0415

        from src.audit.replay.service import TraceDetailService, TraceNotFoundInIndexError  # noqa: PLC0415
        from src.audit.trace.object_store import TraceObjectStore  # noqa: PLC0415
        from src.audit.trace.repository import TraceIndexRepository  # noqa: PLC0415
        from src.data.database import primary_session_factory  # noqa: PLC0415
        from src.data.redis_client import create_redis_client  # noqa: PLC0415

        request_id = _uuid.UUID(execution_id)
        redis_client = create_redis_client()
        async with primary_session_factory()() as session:
            service = TraceDetailService(
                index_repo=TraceIndexRepository(session),
                object_store=TraceObjectStore(),
                cache=redis_client,
            )
            try:
                detail = await service.get_detail("default", request_id)
                return _with_replay_compatibility(
                    build_tool_response(
                    status="success",
                    summary="Execution trace retrieved.",
                    data={"execution_id": execution_id, "trace": detail.model_dump(mode="json")},
                    diagnostics={"adapter": "trace_replay", "trace_found": True},
                    )
                )
            except TraceNotFoundInIndexError:
                return _with_replay_compatibility(
                    build_tool_response(
                    status="empty",
                    summary="No execution trace was found for the supplied execution ID.",
                    data={"execution_id": execution_id, "trace": None},
                    diagnostics={"adapter": "trace_replay", "trace_found": False},
                    )
                )
            finally:
                await redis_client.aclose()
    except Exception as exc:
        return _with_replay_compatibility(
            build_error_response(
                summary="Execution replay is unavailable because the trace backend could not be queried.",
                error=exc,
                diagnostics={"adapter": "trace_replay", "execution_id": execution_id},
            ),
            execution_id=execution_id,
        )


async def _build_workspace_fallback_context_payload(
    *,
    prompt: str,
    max_tokens: int,
    compression_level: str,
    degraded_reason: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    intent = _heuristic_intent(prompt)
    limit = min(max(max_tokens // 450, 4), 16)
    repo_matches = search_workspace(prompt, roots=CODE_ROOTS + [DOC_ROOT], limit=limit)
    masked_matches, governance = _apply_governance_masking(repo_matches)
    compressed_matches, compression = _compress_matches(
        masked_matches,
        max_tokens=max_tokens,
        compression_level=compression_level,
        method="workspace_ranked_truncate",
    )
    routing = await _build_routing_metadata(
        prompt=prompt,
        intent=intent,
        context_items=compressed_matches,
        governance=governance,
        requested_tool="generate_context",
    )
    sources = sorted({match["path"].split("/", 1)[0] for match in compressed_matches})
    status = "success" if compressed_matches else "empty"
    summary = (
        f"Retrieved {len(compressed_matches)} workspace context item(s) using local fallback retrieval."
        if compressed_matches
        else "No workspace matches were found for the request; fallback retrieval completed without errors."
    )
    response = build_tool_response(
        status=status,
        summary=summary,
        data={
            "prompt": prompt,
            "intent": intent,
            "context": compressed_matches,
            "sources": sources,
            "ranking": {
                "strategy": "workspace_token_path_hybrid",
                "returned_items": len(compressed_matches),
            },
        },
        diagnostics={
            "adapter": "workspace_fallback",
            "requested_max_tokens": max_tokens,
            "compression_level": compression_level,
            "source_availability": workspace_coverage(roots=CODE_ROOTS + [DOC_ROOT]),
            "degraded_reasons": [degraded_reason],
            "retrieval": {
                "matches_found": len(repo_matches),
                "returned_matches": len(compressed_matches),
            },
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
        governance=governance,
        routing=routing,
        compression=compression,
    )
    return _with_generate_context_compatibility(response)


async def _normalise_pipeline_context_payload(
    pipeline_result: dict[str, Any],
    *,
    prompt: str,
    max_tokens: int,
    compression_level: str,
) -> dict[str, Any]:
    final_response = pipeline_result.get("final_response") if isinstance(pipeline_result.get("final_response"), dict) else {}
    active_context = _extract_context_items(pipeline_result, final_response)
    tokens_before = pipeline_result.get("tokens_before_compression")
    if tokens_before is None:
        pre_context = pipeline_result.get("ranked_context_pre_compression") or pipeline_result.get("ranked_context") or active_context
        tokens_before = _count_context_tokens(pre_context)
    tokens_after = pipeline_result.get("tokens_after_compression")
    if tokens_after is None:
        tokens_after = _count_context_tokens(active_context)

    governance = _governance_section_from_pipeline(pipeline_result, final_response)
    routing = await _build_routing_metadata(
        prompt=prompt,
        intent=str(pipeline_result.get("intent_type") or final_response.get("intent") or _heuristic_intent(prompt)),
        context_items=active_context,
        governance=governance,
        requested_tool="generate_context",
        preferred_model=str(pipeline_result.get("selected_model") or final_response.get("selected_model") or ""),
        preferred_score=float(pipeline_result.get("model_routing_score") or final_response.get("model_routing_score") or 0.0),
        candidate_models=list(pipeline_result.get("fallback_chain") or final_response.get("fallback_chain") or []),
    )
    compression = {
        "enabled": bool(
            pipeline_result.get("tokens_before_compression") is not None
            or pipeline_result.get("tokens_after_compression") is not None
            or (tokens_before and tokens_after and tokens_before != tokens_after)
        ),
        "method": "langgraph_pipeline" if pipeline_result.get("tokens_before_compression") is not None else "computed_from_pipeline_state",
        "tokens_before": int(tokens_before or 0),
        "tokens_after": int(tokens_after or 0),
        "ratio": _compression_ratio(int(tokens_before or 0), int(tokens_after or 0)),
    }

    degraded_sources = list(final_response.get("degraded_sources") or pipeline_result.get("degraded_sources") or [])
    status = "success" if (final_response or active_context) else "empty"
    if status == "success" and (degraded_sources or final_response.get("invocation_error")):
        status = "degraded"

    summary = _pipeline_summary(final_response, active_context, degraded_sources)
    response = build_tool_response(
        status=status,
        summary=summary,
        data={
            "prompt": prompt,
            "intent": str(pipeline_result.get("intent_type") or final_response.get("intent") or _heuristic_intent(prompt)),
            "context": active_context,
            "sources": sorted(_source_ids_from_context(active_context)),
            "ranking": {
                "strategy": getattr(pipeline_result.get("execution_plan"), "ranking_strategy", None)
                if pipeline_result.get("execution_plan") is not None
                else None,
                "returned_items": len(active_context),
            },
            "answer": final_response.get("answer"),
        },
        diagnostics={
            "adapter": "langgraph_pipeline",
            "requested_max_tokens": max_tokens,
            "compression_level": compression_level,
            "current_node": pipeline_result.get("current_node"),
            "source_availability": {
                "degraded_sources": degraded_sources,
                "graph_status": str(pipeline_result.get("status") or "unknown"),
            },
            "degraded_reasons": _pipeline_degraded_reasons(final_response, degraded_sources),
        },
        governance=governance,
        routing=routing,
        compression=compression,
    )
    return _with_generate_context_compatibility(response)


def _normalise_context_payload(
    payload: dict[str, Any],
    *,
    prompt: str,
    max_tokens: int,
    compression_level: str,
    adapter: str,
) -> dict[str, Any]:
    if {"status", "summary", "data", "diagnostics"}.issubset(payload.keys()):
        normalised = dict(payload)
        diagnostics = dict(normalised.get("diagnostics") or {})
        diagnostics.setdefault("adapter", adapter)
        normalised["diagnostics"] = diagnostics
        return _with_generate_context_compatibility(normalised)

    context_block = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    context_items = context_block.get("context") if isinstance(context_block.get("context"), list) else []
    routing = {
        "selected_model": payload.get("selected_model"),
        "candidate_models": [],
        "rationale": payload.get("routing_reason") or "Provided by injected context service.",
        "routing_score": float(payload.get("model_routing_score") or 0.0),
        "confidence": float(payload.get("model_routing_score") or 0.0),
    }
    compression = {
        "enabled": payload.get("tokens_before_compression") is not None,
        "method": "context_service",
        "tokens_before": int(payload.get("tokens_before_compression") or _count_context_tokens(context_items)),
        "tokens_after": int(payload.get("tokens_after_compression") or _count_context_tokens(context_items)),
        "ratio": _compression_ratio(
            int(payload.get("tokens_before_compression") or _count_context_tokens(context_items)),
            int(payload.get("tokens_after_compression") or _count_context_tokens(context_items)),
        ),
    }
    normalised = build_tool_response(
        status=str(payload.get("status") or ("success" if context_items else "empty")),
        summary="Context retrieved by the injected context service." if context_items else "The injected context service returned no context items.",
        data={
            "prompt": prompt,
            "intent": str(context_block.get("intent") or _heuristic_intent(prompt)),
            "context": context_items,
            "sources": list(context_block.get("sources") or []),
            "ranking": {"strategy": "service_defined", "returned_items": len(context_items)},
        },
        diagnostics={
            "adapter": adapter,
            "requested_max_tokens": max_tokens,
            "compression_level": compression_level,
            "degraded_reasons": [],
        },
        governance=payload.get("governance") if isinstance(payload.get("governance"), dict) else {},
        routing=routing,
        compression=compression,
    )
    return _with_generate_context_compatibility(normalised)


def _normalise_replay_payload(payload: dict[str, Any], execution_id: str, *, adapter: str) -> dict[str, Any]:
    if {"status", "summary", "data", "diagnostics"}.issubset(payload.keys()):
        diagnostics = dict(payload.get("diagnostics") or {})
        diagnostics.setdefault("adapter", adapter)
        payload["diagnostics"] = diagnostics
        return _with_replay_compatibility(payload, execution_id=execution_id)

    trace = payload.get("trace")
    status = str(payload.get("status") or ("success" if trace else "empty"))
    summary = "Execution trace retrieved." if trace else "No execution trace was found for the supplied execution ID."
    return _with_replay_compatibility(build_tool_response(
        status="empty" if status == "not_found" else status,
        summary=summary,
        data={"execution_id": execution_id, "trace": trace},
        diagnostics={"adapter": adapter, "trace_found": trace is not None},
    ), execution_id=execution_id)


def _extract_context_items(pipeline_result: dict[str, Any], final_response: dict[str, Any]) -> list[dict[str, Any]]:
    final_context = final_response.get("context")
    if isinstance(final_context, list):
        return [item for item in final_context if isinstance(item, dict)]

    ranked = pipeline_result.get("compressed_context") or pipeline_result.get("ranked_context") or []
    return [item for item in ranked if isinstance(item, dict)]


def _governance_section_from_pipeline(
    pipeline_result: dict[str, Any],
    final_response: dict[str, Any],
) -> dict[str, Any]:
    summary = final_response.get("governance", {}).get("summary") if isinstance(final_response.get("governance"), dict) else None
    if summary is None:
        summary = pipeline_result.get("governance_summary")
    masked_items = {}
    if isinstance(summary, dict):
        audit_log = summary.get("audit_log")
        if isinstance(audit_log, dict):
            masked_items = dict(audit_log.get("masked_items") or {})
    return {
        "blocked": bool(final_response.get("governance", {}).get("blocked") if isinstance(final_response.get("governance"), dict) else pipeline_result.get("governance_blocked")),
        "redacted": bool(final_response.get("governance", {}).get("redacted") if isinstance(final_response.get("governance"), dict) else pipeline_result.get("context_redacted")),
        "findings_count": len(pipeline_result.get("governance_findings") or []),
        "masking_counts": masked_items,
        "summary": summary,
    }


async def _build_routing_metadata(
    *,
    prompt: str,
    intent: str,
    context_items: list[dict[str, Any]],
    governance: dict[str, Any],
    requested_tool: str,
    preferred_model: str | None = None,
    preferred_score: float | None = None,
    candidate_models: list[str] | None = None,
) -> dict[str, Any]:
    candidates = await _candidate_models(candidate_models)
    prompt_tokens = count_tokens(prompt)
    context_tokens = _count_context_tokens(context_items)
    complexity = prompt_tokens + context_tokens
    governance_pressure = int(sum((governance.get("masking_counts") or {}).values()))
    intent_lower = intent.lower()

    scored_candidates = []
    for candidate in candidates:
        score = 0.2
        reasons: list[str] = []
        model_id = str(candidate["model_id"])
        latency = str(candidate.get("latency_tier") or _latency_hint(model_id))
        capabilities = {str(value).lower() for value in (candidate.get("capabilities") or _capability_hints(model_id))}
        context_window = int(candidate.get("context_window") or _context_window_hint(model_id))
        cost = float(candidate.get("cost_per_1k_tokens") or _cost_hint(model_id))

        if preferred_model and model_id == preferred_model and (preferred_score or 0.0) > 0:
            score += min(float(preferred_score), 1.0)
            reasons.append("selected by configured routing pipeline")
        if complexity > 1600 or governance_pressure > 0 or intent_lower in {"architecture", "debugging", "code-gen"}:
            if "code" in capabilities or "chat" in capabilities:
                score += 0.45
                reasons.append("better suited for complex retrieved context")
            if latency != "fast":
                score += 0.1
                reasons.append("higher-quality latency tier acceptable")
        else:
            if latency == "fast":
                score += 0.35
                reasons.append("favours low-latency response for lighter request")
            if "mini" in model_id or "haiku" in model_id:
                score += 0.15
                reasons.append("lightweight model matches simple request")
        if context_window >= max(complexity + 512, 1024):
            score += 0.2
            reasons.append("context window can hold retrieved material")
        if requested_tool == "generate_context":
            score += 0.1
            reasons.append("tool only needs context packaging rather than full final answer")
        score -= min(cost / 100.0, 0.15)
        scored_candidates.append(
            {
                "model_id": model_id,
                "score": round(max(min(score, 1.0), 0.0), 4),
                "latency_tier": latency,
                "capabilities": sorted(capabilities),
                "reasons": reasons,
            }
        )

    scored_candidates.sort(key=lambda item: item["score"], reverse=True)
    selected = scored_candidates[0] if scored_candidates else {
        "model_id": preferred_model or _ROUTING_SETTINGS.fallback_model_id,
        "score": 0.0,
        "reasons": ["no model candidates were available"],
    }
    rationale = "; ".join(selected.get("reasons") or ["no routing rationale available"])
    return {
        "selected_model": selected["model_id"],
        "candidate_models": scored_candidates,
        "rationale": rationale,
        "routing_score": float(selected["score"]),
        "confidence": float(selected["score"]),
    }


async def _candidate_models(explicit_candidates: list[str] | None = None) -> list[dict[str, Any]]:
    candidate_models: list[dict[str, Any]] = []
    seen: set[str] = set()

    for model_id in explicit_candidates or []:
        if model_id and model_id not in seen:
            seen.add(model_id)
            candidate_models.append({"model_id": model_id})

    try:
        from src.data.database import primary_session_factory  # noqa: PLC0415
        from src.model_registry.repositories.model_repository import ModelRepository  # noqa: PLC0415
        from src.model_registry.schemas.model_definition import ModelDefinition  # noqa: PLC0415

        async with primary_session_factory()() as session:
            records = await ModelRepository(session).list_active()
        for record in records:
            model = ModelDefinition.model_validate(record)
            if model.model_id in seen:
                continue
            seen.add(model.model_id)
            candidate_models.append(model.model_dump(mode="python"))
    except Exception:
        logger.debug("generate_context routing candidate discovery fell back to settings defaults", exc_info=True)

    for model_id in [agent_settings.llm_model_id, _ROUTING_SETTINGS.fallback_model_id]:
        if model_id and model_id not in seen:
            seen.add(model_id)
            candidate_models.append({"model_id": model_id})

    return candidate_models


def _apply_governance_masking(matches: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from src.governance.detection.detector import SecretPIIDetector  # noqa: PLC0415
        from src.governance.detection.redactor import ContextRedactor  # noqa: PLC0415
    except Exception:
        return matches, {"blocked": False, "redacted": False, "findings_count": 0, "masking_counts": {}}

    scan_input = [
        {
            "chunk_id": f"{match.get('path')}:{match.get('line')}",
            "text": str(match.get("snippet") or ""),
        }
        for match in matches
    ]
    try:
        scan_result = SecretPIIDetector().scan_context(scan_input)
    except Exception:
        logger.warning("generate_context fallback governance scan failed; returning unmasked context", exc_info=True)
        return matches, {"blocked": False, "redacted": False, "findings_count": 0, "masking_counts": {}}

    updated_input, _redaction_results = ContextRedactor().redact_context(scan_input, scan_result)
    replacements = {item["chunk_id"]: item["text"] for item in updated_input}
    redacted_matches = []
    for match in matches:
        chunk_id = f"{match.get('path')}:{match.get('line')}"
        redacted_matches.append({**match, "snippet": replacements.get(chunk_id, str(match.get("snippet") or ""))})

    counts = Counter(finding.pattern_type.value for finding in scan_result.findings)
    return redacted_matches, {
        "blocked": False,
        "redacted": bool(scan_result.findings),
        "findings_count": len(scan_result.findings),
        "masking_counts": dict(counts),
    }


def _compress_matches(
    matches: list[dict[str, Any]],
    *,
    max_tokens: int,
    compression_level: str,
    method: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tokens_before = _count_context_tokens(matches)
    budget_ratio = {"low": 1.0, "medium": 0.85, "high": 0.65}.get(compression_level, 0.85)
    target_budget = max(256, min(max_tokens, int(max_tokens * budget_ratio)))
    compressed: list[dict[str, Any]] = []
    running_tokens = 0
    for match in matches:
        snippet = str(match.get("snippet") or "")
        snippet_tokens = count_tokens(snippet)
        if running_tokens + snippet_tokens <= target_budget:
            compressed.append(match)
            running_tokens += snippet_tokens
            continue
        remaining = max(target_budget - running_tokens, 0)
        if remaining <= 24:
            break
        trimmed_snippet = _truncate_to_token_budget(snippet, remaining)
        if trimmed_snippet:
            compressed.append({**match, "snippet": trimmed_snippet, "truncated": True})
            running_tokens += count_tokens(trimmed_snippet)
        break

    tokens_after = _count_context_tokens(compressed)
    return compressed, {
        "enabled": tokens_before > tokens_after,
        "method": method,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "ratio": _compression_ratio(tokens_before, tokens_after),
    }


def _truncate_to_token_budget(text: str, budget: int) -> str:
    words = text.split()
    if count_tokens(text) <= budget:
        return text
    if budget <= 0:
        return ""
    trimmed_words: list[str] = []
    for word in words:
        candidate = " ".join(trimmed_words + [word])
        if count_tokens(candidate) > budget:
            break
        trimmed_words.append(word)
    return " ".join(trimmed_words).strip()


def _count_context_tokens(items: list[Any]) -> int:
    total = 0
    for item in items:
        if isinstance(item, dict):
            text = item.get("content") or item.get("text") or item.get("snippet") or item.get("summary") or item.get("value") or ""
        else:
            text = str(item)
        total += count_tokens(str(text))
    return total


def _source_ids_from_context(items: list[dict[str, Any]]) -> set[str]:
    source_ids = set()
    for item in items:
        for field in ("source_id", "source", "path"):
            value = item.get(field)
            if isinstance(value, str) and value:
                source_ids.add(value.split("/", 1)[0] if field == "path" else value)
                break
    return source_ids


def _compression_ratio(tokens_before: int, tokens_after: int) -> float | None:
    if tokens_before <= 0:
        return None
    return round(tokens_after / tokens_before, 4)


def _pipeline_summary(
    final_response: dict[str, Any],
    active_context: list[dict[str, Any]],
    degraded_sources: list[Any],
) -> str:
    if not active_context:
        return "The pipeline completed without retrieving usable context for this request."
    if final_response.get("answer"):
        return f"Retrieved {len(active_context)} context item(s) and generated an answer."
    if degraded_sources:
        return f"Retrieved {len(active_context)} context item(s), but one or more pipeline dependencies degraded."
    return f"Retrieved {len(active_context)} context item(s) through the LangGraph pipeline."


def _pipeline_degraded_reasons(final_response: dict[str, Any], degraded_sources: list[Any]) -> list[str]:
    reasons: list[str] = []
    if final_response.get("invocation_error"):
        reasons.append(str(final_response["invocation_error"]))
    for source in degraded_sources:
        if isinstance(source, dict) and source.get("message"):
            reasons.append(str(source["message"]))
        elif source:
            reasons.append(str(source))
    return reasons


def _with_generate_context_compatibility(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") or {}
    routing = response.get("routing") or {}
    compression = response.get("compression") or {}
    diagnostics = response.get("diagnostics") or {}
    adapter = diagnostics.get("adapter")
    mode = {
        "langgraph_pipeline": "pipeline",
        "workspace_fallback": "workspace_fallback",
        "context_service": "service",
    }.get(adapter, adapter)
    compat = dict(response)
    compat.update(
        {
            "prompt": data.get("prompt"),
            "mode": mode,
            "context": {
                "type": "context_package",
                "intent": data.get("intent"),
                "context": data.get("context") or [],
                "sources": data.get("sources") or [],
                "answer": data.get("answer"),
                "governance": response.get("governance") or {},
            },
            "selected_model": routing.get("selected_model"),
            "model_routing_score": routing.get("routing_score"),
            "tokens_before_compression": compression.get("tokens_before"),
            "tokens_after_compression": compression.get("tokens_after"),
        }
    )
    return compat


def _with_replay_compatibility(response: dict[str, Any], execution_id: str | None = None) -> dict[str, Any]:
    data = response.get("data") or {}
    compat = dict(response)
    compat["execution_id"] = data.get("execution_id") or execution_id
    compat["trace"] = data.get("trace")
    return compat


def _latency_hint(model_id: str) -> str:
    lowered = model_id.lower()
    if any(token in lowered for token in ["mini", "haiku", "flash"]):
        return "fast"
    if any(token in lowered for token in ["gpt-4o", "claude-3", "sonnet", "llama"]):
        return "medium"
    return "slow"


def _capability_hints(model_id: str) -> list[str]:
    lowered = model_id.lower()
    capabilities = ["chat"]
    if any(token in lowered for token in ["code", "gpt", "claude", "llama"]):
        capabilities.append("code")
    return capabilities


def _context_window_hint(model_id: str) -> int:
    lowered = model_id.lower()
    if any(token in lowered for token in ["gpt-4o", "claude", "sonnet"]):
        return 128_000
    if "mini" in lowered:
        return 32_000
    return 16_000


def _cost_hint(model_id: str) -> float:
    lowered = model_id.lower()
    if lowered.startswith("ollama/"):
        return 0.0
    if "mini" in lowered or "haiku" in lowered:
        return 0.5
    if any(token in lowered for token in ["gpt-4o", "claude", "sonnet"]):
        return 5.0
    return 2.0


def _heuristic_intent(prompt: str) -> str:
    lowered = prompt.lower()
    if any(token in lowered for token in ["error", "bug", "fix", "failing"]):
        return "debugging"
    if any(token in lowered for token in ["architecture", "design", "system"]):
        return "architecture"
    if any(token in lowered for token in ["doc", "readme", "documentation"]):
        return "docs"
    return "general"
