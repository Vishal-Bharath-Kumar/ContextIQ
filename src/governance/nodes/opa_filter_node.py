"""opa_filter_node — LangGraph OPA Policy Enforcement Gate (TASK-US032-04).

Position: after governance_node (US-031), before routing/compression node.

Evaluates every context chunk against OPA ``data.contextiq.authz.allow``,
filters denied chunks (AC-3), records each decision in execution_trace (AC-4),
and increments ``governance_policy_denials_total`` (AC-7).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry import trace

from src.agents.state import AgentState
from src.governance.opa.metrics import (
    governance_policy_denials_total,
    opa_evaluation_duration_ms,
)
from src.governance.opa.schemas import AuthzFilterResult, ChunkAuthzInput

if TYPE_CHECKING:
    from src.governance.opa.client import OPAClient

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
_langfuse = None


def _get_langfuse() -> object | None:
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    try:
        from langfuse import Langfuse  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        logger.warning("opa_filter_node: Langfuse unavailable: %s", exc)
        return None
    try:
        _langfuse = Langfuse()
    except Exception as exc:  # noqa: BLE001
        logger.warning("opa_filter_node: Langfuse init failed: %s", exc)
        return None
    return _langfuse

# Module-level singleton for production use (set at lifespan startup).
_DEFAULT_OPA_CLIENT: OPAClient | None = None


def set_opa_client(client: OPAClient) -> None:
    """Inject the shared OPAClient at lifespan startup."""
    global _DEFAULT_OPA_CLIENT
    _DEFAULT_OPA_CLIENT = client


async def opa_filter_node(state: AgentState) -> dict:
    """LangGraph node — OPA Policy Enforcement Gate.

    Steps:
    1. Build a ChunkAuthzInput per ranked_context item.
    2. Call OPAClient.evaluate_batch() concurrently.
    3. Filter denied chunks from ranked_context (AC-3).
    4. Record each decision in execution_trace (AC-4).
    5. Increment governance_policy_denials_total for each denial (AC-7).
    6. Emit OTel span and Langfuse event.

    OPAClient is retrieved from state["_config"]["opa_client"] first, then
    falls back to the module-level singleton.  If neither is available,
    OPAEvaluationError propagates — fail-safe, no silent allow.
    """
    ranked_context: list[dict] = state.get("ranked_context") or []
    tenant_id: str = state.get("tenant_id") or "default"
    user_roles: list[str] = _extract_user_roles(state)

    with tracer.start_as_current_span("governance.opa_filter") as span:
        span.set_attribute("opa.chunks_to_evaluate", len(ranked_context))
        span.set_attribute("opa.tenant_id", tenant_id)

        if not ranked_context:
            return {
                "opa_decisions": [],
                "opa_denied_count": 0,
                "opa_bundle_version": _get_bundle_version(state),
                "execution_trace": state.get("execution_trace") or [],
                "status": state.get("status"),
                "current_node": "opa_filter",
            }

        inputs = [
            _build_authz_input(item, idx, user_roles, tenant_id)
            for idx, item in enumerate(ranked_context)
        ]

        opa_client: OPAClient = _resolve_opa_client(state)
        bundle_version = _get_bundle_version(state)

        filter_result: AuthzFilterResult = await opa_client.evaluate_batch(inputs)
        # Attach bundle_version (not set by the client itself).
        dumped = filter_result.model_dump()
        dumped["bundle_version"] = bundle_version
        filter_result = AuthzFilterResult(**dumped)

        # ── Prometheus metrics ─────────────────────────────────────────
        for decision in filter_result.decisions:
            label = "allow" if decision.allow else "deny"
            opa_evaluation_duration_ms.labels(result=label).observe(decision.eval_ms)

        for decision in filter_result.decisions:
            if decision.is_denied:
                orig = next(
                    (
                        item
                        for item in ranked_context
                        if _chunk_key(item, ranked_context.index(item)) == decision.chunk_id
                    ),
                    None,
                )
                classification = (
                    (orig.get("metadata") or {}).get("classification_label", "internal")
                    if orig
                    else "internal"
                )
                governance_policy_denials_total.labels(
                    tenant_id=tenant_id,
                    classification_label=classification,
                ).inc()

        # ── Filter denied chunks (AC-3) ────────────────────────────────
        denied_set = set(filter_result.denied_chunk_ids)
        allowed_chunks = [
            item
            for idx, item in enumerate(ranked_context)
            if _chunk_key(item, idx) not in denied_set
        ]

        span.set_attribute("opa.allowed_count", len(allowed_chunks))
        span.set_attribute("opa.denied_count", filter_result.denial_count)
        span.set_attribute("opa.eval_ms", filter_result.total_eval_ms)

        # ── execution_trace entry (AC-4) ───────────────────────────────
        _record_trace(state, filter_result)

        langfuse = _get_langfuse()
        if langfuse is not None:
            langfuse.create_event(
                name="opa_policy_evaluation",
                input={"chunks": len(ranked_context), "tenant_id": tenant_id},
                output={
                    "allowed": len(allowed_chunks),
                    "denied": filter_result.denial_count,
                    "eval_ms": filter_result.total_eval_ms,
                },
                metadata={"bundle_version": bundle_version},
            )

        if filter_result.denial_count:
            logger.warning(
                "opa_filter_node: %d chunk(s) denied for tenant=%s. Denied IDs: %s",
                filter_result.denial_count,
                tenant_id,
                filter_result.denied_chunk_ids[:5],
            )

        return {
            "ranked_context": allowed_chunks,
            "opa_decisions": list(filter_result.decisions),
            "opa_denied_count": filter_result.denial_count,
            "opa_bundle_version": bundle_version,
            "execution_trace": state.get("execution_trace") or [],
            "status": state.get("status"),
            "current_node": "opa_filter",
        }


# ── Private helpers ─────────────────────────────────────────────────────────


def _extract_user_roles(state: AgentState) -> list[str]:
    jwt_claims: dict = state.get("jwt_claims") or {}
    roles_from_claims = list(
        jwt_claims.get("roles")
        or jwt_claims.get("realm_access", {}).get("roles", [])
    )
    # Fall back to the top-level roles field already populated by the execute handler.
    return roles_from_claims or list(state.get("roles") or [])


def _build_authz_input(
    item: dict,
    idx: int,
    user_roles: list[str],
    tenant_id: str,
) -> ChunkAuthzInput:
    metadata = item.get("metadata") or {}
    return ChunkAuthzInput(
        user_roles=user_roles,
        tenant_id=tenant_id,
        source_id=str(item.get("source_id") or ""),
        chunk_id=_chunk_key(item, idx),
        document_id=str(item.get("document_id") or ""),
        classification_label=metadata.get("classification_label", "internal"),
    )


def _chunk_key(item: dict, idx: int) -> str:
    return str(item.get("chunk_id") or item.get("id") or idx)


def _resolve_opa_client(state: AgentState) -> OPAClient:
    config: dict = state.get("_config") or {}
    client = config.get("opa_client") or _DEFAULT_OPA_CLIENT
    if client is None:
        from src.governance.opa.client import OPAEvaluationError

        raise OPAEvaluationError(
            "OPAClient is not initialised. "
            "Inject via state['_config']['opa_client'] or call set_opa_client()."
        )
    return client  # type: ignore[return-value]


def _get_bundle_version(state: AgentState) -> str:
    config: dict = state.get("_config") or {}
    hot_reloader = config.get("hot_reloader")
    if hot_reloader is not None:
        return hot_reloader.current_bundle.version
    return "unknown"


def _record_trace(state: AgentState, result: AuthzFilterResult) -> None:
    """Append OPA decisions to execution_trace (AC-4)."""
    trace_entry = {
        "node": "opa_filter",
        "eval_ms": result.total_eval_ms,
        "bundle_version": result.bundle_version,
        "decisions": [
            {
                "chunk_id": d.chunk_id,
                "allow": d.allow,
                "rationale": d.rationale,
                "eval_ms": d.eval_ms,
            }
            for d in result.decisions
        ],
    }
    existing: list = state.get("execution_trace") or []
    state["execution_trace"] = existing + [trace_entry]
