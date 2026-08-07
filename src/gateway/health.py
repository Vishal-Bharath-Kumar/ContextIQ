"""Helpers for exposing gateway knowledge-graph runtime state on health endpoints."""

from __future__ import annotations

from typing import Any


def default_knowledge_graph_health_status() -> dict[str, Any]:
    return {
        "status": "unknown",
        "configured": False,
        "neo4j_store_ready": False,
        "entity_consumer_running": False,
        "graph_updater_running": False,
    }


def knowledge_graph_health_status(
    *,
    configured: bool,
    neo4j_store_ready: bool,
    entity_consumer_running: bool,
    graph_updater_running: bool,
) -> dict[str, Any]:
    return {
        "status": _knowledge_graph_status_value(
            configured=configured,
            neo4j_store_ready=neo4j_store_ready,
            entity_consumer_running=entity_consumer_running,
            graph_updater_running=graph_updater_running,
        ),
        "configured": configured,
        "neo4j_store_ready": neo4j_store_ready,
        "entity_consumer_running": entity_consumer_running,
        "graph_updater_running": graph_updater_running,
    }


def build_knowledge_graph_health_status(state: Any) -> dict[str, Any]:
    return knowledge_graph_health_status(
        configured=bool(getattr(state, "knowledge_graph_configured", False)),
        neo4j_store_ready=hasattr(state, "neo4j_store"),
        entity_consumer_running=_task_running(getattr(state, "entity_consumer_task", None)),
        graph_updater_running=_task_running(getattr(state, "graph_updater_task", None)),
    )


def _knowledge_graph_status_value(
    *,
    configured: bool,
    neo4j_store_ready: bool,
    entity_consumer_running: bool,
    graph_updater_running: bool,
) -> str:
    if not configured:
        return "disabled"

    if neo4j_store_ready and entity_consumer_running and graph_updater_running:
        return "ready"

    if neo4j_store_ready or entity_consumer_running or graph_updater_running:
        return "degraded"

    return "unready"


def _task_running(task: Any) -> bool:
    return bool(task is not None and hasattr(task, "done") and not task.done())