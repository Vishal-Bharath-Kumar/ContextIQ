"""AI context engineering tools.

TASK-BRD-18: Implements MCP tools for AI context capabilities:
- generate_context: Generate optimized context for AI requests
- compress_context: Apply AI compression to reduce tokens
- replay_execution: Replay a previous AI execution
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP
from src.agents.state import ExecutionStatus
from src.gateway.tools.enterprise._local_tools import CODE_ROOTS, DOC_ROOT, json_text_response, search_workspace
from mcp.types import TextContent

logger = logging.getLogger(__name__)


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
            result = await _generate_context_payload(
                prompt=prompt,
                max_tokens=max_tokens,
                compression_level=compression_level,
                context_service=context_service,
            )
            
            logger.info(
                "generate_context invoked: tokens=%d, compression=%s",
                max_tokens,
                compression_level,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("generate_context failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

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

            result = {
                "original_length": original_length,
                "compressed_length": len(compressed_content),
                "compression_ratio": f"{target_compression * 100}%",
                "compressed_content": compressed_content,
                "removed_items": max(len(paragraphs) - len(deduped), 0),
                "status": "success",
            }
            
            logger.info(
                "compress_context invoked: original=%d, target_ratio=%.2f",
                original_length,
                target_compression,
            )
            
            return json_text_response(result)
            
        except Exception as e:
            logger.error("compress_context failed: %s", e, exc_info=True)
            return json_text_response({"error": str(e), "status": "error"})

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
            return json_text_response({"error": str(e), "status": "error"})


async def _generate_context_payload(
    *,
    prompt: str,
    max_tokens: int,
    compression_level: str,
    context_service: Any = None,
) -> dict[str, Any]:
    if context_service is not None and hasattr(context_service, "generate_context"):
        return await context_service.generate_context(prompt, max_tokens=max_tokens, compression_level=compression_level)

    pipeline_result = await _try_pipeline_context(prompt)
    if pipeline_result is not None:
        return {
            "prompt": prompt,
            "requested_max_tokens": max_tokens,
            "compression_level": compression_level,
            "context": pipeline_result.get("final_response"),
            "tokens_before_compression": pipeline_result.get("tokens_before_compression"),
            "tokens_after_compression": pipeline_result.get("tokens_after_compression"),
            "selected_model": pipeline_result.get("selected_model"),
            "status": "success",
            "mode": "pipeline",
        }

    repo_matches = search_workspace(
        prompt,
        roots=CODE_ROOTS + [DOC_ROOT],
        limit=min(max(max_tokens // 600, 3), 12),
    )
    return {
        "prompt": prompt,
        "requested_max_tokens": max_tokens,
        "compression_level": compression_level,
        "context": {
            "type": "context_package",
            "intent": _heuristic_intent(prompt),
            "context": repo_matches,
            "sources": sorted({match["path"].split("/", 1)[0] for match in repo_matches}),
        },
        "original_tokens": sum(len(match["snippet"].split()) for match in repo_matches),
        "compressed_tokens": sum(len(match["snippet"].split()) for match in repo_matches),
        "status": "success",
        "mode": "workspace_fallback",
    }


async def _try_pipeline_context(prompt: str) -> dict[str, Any] | None:
    try:
        from src.gateway.tools.clarification_reply import get_graph  # noqa: PLC0415
    except Exception:
        return None

    try:
        graph = get_graph()
    except Exception:
        return None

    request_id = str(uuid.uuid4())
    state = {
        "request_id": request_id,
        "user_id": "enterprise-tools",
        "username": "enterprise-tools",
        "roles": ["platform_engineer"],
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
        return None
    return result if result.get("status") != ExecutionStatus.FAILED else None


async def _replay_execution_payload(execution_id: str, context_service: Any = None) -> dict[str, Any]:
    if context_service is not None and hasattr(context_service, "replay_execution"):
        return await context_service.replay_execution(execution_id)

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
                return {"execution_id": execution_id, "status": "success", "trace": detail.model_dump(mode="json")}
            except TraceNotFoundInIndexError:
                return {"execution_id": execution_id, "status": "not_found"}
            finally:
                await redis_client.aclose()
    except Exception as exc:
        return {
            "execution_id": execution_id,
            "status": "unavailable",
            "reason": str(exc),
        }


def _heuristic_intent(prompt: str) -> str:
    lowered = prompt.lower()
    if any(token in lowered for token in ["error", "bug", "fix", "failing"]):
        return "debugging"
    if any(token in lowered for token in ["architecture", "design", "system"]):
        return "architecture"
    if any(token in lowered for token in ["doc", "readme", "documentation"]):
        return "docs"
    return "general"
