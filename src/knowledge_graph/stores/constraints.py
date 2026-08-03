"""Neo4j uniqueness constraint definitions for entity node labels.

Constraints are created once at application lifespan startup (idempotent via
``IF NOT EXISTS``).  Each ``EntityType`` gets its own label, enabling
label-specific indexes for US-029 graph traversal performance.
"""
from __future__ import annotations

ENTITY_TYPES: list[str] = [
    "Service",
    "Repository",
    "Developer",
    "Incident",
    "Deployment",
    "AlertRule",
    "Document",
]

CONSTRAINT_STATEMENTS: list[str] = [
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{entity_type}) "
    f"REQUIRE n.entity_id IS UNIQUE"
    for entity_type in ENTITY_TYPES
]
