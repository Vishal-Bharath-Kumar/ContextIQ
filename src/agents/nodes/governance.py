"""Governance node — re-exports the canonical implementation from governance package."""

from src.governance.nodes.governance_node import governance_node

__all__ = ["governance_node"]
