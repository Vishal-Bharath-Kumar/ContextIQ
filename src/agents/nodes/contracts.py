"""Per-node output field declarations for the ContextIQ multi-agent pipeline.

Each entry declares the *only* fields a node is permitted to write back into
``AgentState``.  The universal fields ``status``, ``current_node``, and
``error`` are always permitted and are included explicitly so the set is
self-documenting.

The dict is consumed by the ``@node_contract`` decorator in ``base.py`` and
validated at runtime when ``settings.debug`` is ``True``.

Immutable identity fields — ``request_id``, ``user_id``, ``username``,
``roles``, ``tool_name``, ``prompt``, ``timestamp`` — are intentionally absent
from every node's allowed set; no node may overwrite them.
"""
from __future__ import annotations

NODE_OUTPUT_CONTRACTS: dict[str, set[str]] = {
    "intent_agent": {
        "intent_type",
        "intent_confidence",
        "execution_plan",
        "status",
        "current_node",
        "error",
    },
    "retrieval_agent": {
        "raw_context",
        "ranked_context",
        "degraded_sources",
        "status",
        "current_node",
        "error",
    },
    "governance_agent": {
        "governance_decisions",
        "redacted_chunks",
        "ranked_context",
        "degraded_sources",
        "status",
        "current_node",
        "error",
    },
    "compression_agent": {
        "compressed_context",
        "tokens_before_compression",
        "tokens_after_compression",
        "status",
        "current_node",
        "error",
    },
    "routing_agent": {
        "selected_model",
        "model_routing_score",
        "final_response",
        "status",
        "current_node",
        "error",
    },
}
