# Kafka Consumer Groups

This document lists all Kafka consumer groups registered in ContextIQ, their
subscribed topics, and the owning service.

## Registered Groups

| Consumer Group | Topic(s) | Service | Task |
|---|---|---|---|
| `contextiq-indexing` | `knowledge.source.synced`, `knowledge.document.deleted` | indexing-service | TASK-US027-04 |
| `context-cache-invalidator` | `contextiq.source.sync` | agent-worker | TASK-US013-05 |

## `context-cache-invalidator`

**Service:** agent-worker  
**Class:** `SourceSyncEventConsumer` (`src/retrieval/cache/sync_event_consumer.py`)  
**Topic:** `contextiq.source.sync`  
**Offset policy:** `auto_offset_reset=latest` — only processes events published
after startup; historical re-index events are not replayed.  
**Commit policy:** manual (`enable_auto_commit=False`) — offset committed only
after `ContextCacheStore.invalidate_source()` completes successfully (at-least-once delivery).
