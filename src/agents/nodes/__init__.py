"""Node package for the LangGraph multi-agent pipeline.

Keep this package import-light so tests can import individual node modules
without triggering optional runtime dependencies from unrelated nodes.
"""

from __future__ import annotations

from importlib import import_module


def __getattr__(name: str):
    module_map = {
        "intent_node": "src.agents.nodes.intent",
        "retrieval_node": "src.agents.nodes.retrieval",
        "governance_node": "src.agents.nodes.governance",
        "compression_node": "src.agents.nodes.compression",
        "routing_node": "src.agents.nodes.routing",
    }
    module_name = module_map.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    return getattr(module, name)

__all__ = [
    "intent_node",
    "retrieval_node",
    "governance_node",
    "compression_node",
    "routing_node",
]
