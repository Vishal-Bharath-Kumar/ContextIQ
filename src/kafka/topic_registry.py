"""
Single source of truth for all Kafka topic names, partition counts, and retention.
Imported by bootstrap_topics.py (provisioning) and by producer/consumer code (validation).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TopicSpec:
    name:              str
    partitions:        int
    replication_factor: int
    retention_ms:      int    # -1 = unlimited
    cleanup_policy:    str = "delete"
    consumer_groups:   tuple[str, ...] = field(default_factory=tuple)


# AC-2: canonical topic table
TOPICS: list[TopicSpec] = [
    TopicSpec(
        name="knowledge.source.synced",
        partitions=6,
        replication_factor=3,
        retention_ms=7 * 24 * 60 * 60 * 1000,     # 7 days
        consumer_groups=("indexing-service",),
    ),
    TopicSpec(
        name="knowledge.chunk.indexed",
        partitions=12,
        replication_factor=3,
        retention_ms=7 * 24 * 60 * 60 * 1000,     # 7 days
        consumer_groups=("graph-agent",),
    ),
    TopicSpec(
        name="knowledge.graph.updated",
        partitions=6,
        replication_factor=3,
        retention_ms=7 * 24 * 60 * 60 * 1000,     # 7 days
        consumer_groups=("context-retrieval",),
    ),
    TopicSpec(
        name="contextiq.state.events",
        partitions=12,
        replication_factor=3,
        retention_ms=24 * 60 * 60 * 1000,          # 24 hours
        consumer_groups=("replay-service",),
    ),
    TopicSpec(
        name="contextiq.governance.events",
        partitions=6,
        replication_factor=3,
        retention_ms=30 * 24 * 60 * 60 * 1000,    # 30 days
        consumer_groups=("audit-logger",),
    ),
    TopicSpec(
        name="contextiq.connector.health",
        partitions=3,
        replication_factor=3,
        retention_ms=60 * 60 * 1000,               # 1 hour
        consumer_groups=("health-monitor",),
    ),
]

# Lookup by topic name
TOPIC_MAP: dict[str, TopicSpec] = {t.name: t for t in TOPICS}
