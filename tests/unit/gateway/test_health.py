from __future__ import annotations

from types import SimpleNamespace

from src.gateway.health import (
    build_knowledge_graph_health_status,
    default_knowledge_graph_health_status,
)


class _TaskStub:
    def __init__(self, *, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


def test_default_knowledge_graph_health_status_shape() -> None:
    payload = default_knowledge_graph_health_status()

    assert payload == {
        "status": "unknown",
        "configured": False,
        "neo4j_store_ready": False,
        "entity_consumer_running": False,
        "graph_updater_running": False,
    }


def test_build_knowledge_graph_health_status_disabled_by_default() -> None:
    payload = build_knowledge_graph_health_status(SimpleNamespace())

    assert payload["status"] == "disabled"
    assert payload["configured"] is False


def test_build_knowledge_graph_health_status_ready_when_all_runtime_parts_alive() -> None:
    state = SimpleNamespace(
        knowledge_graph_configured=True,
        neo4j_store=object(),
        entity_consumer_task=_TaskStub(done=False),
        graph_updater_task=_TaskStub(done=False),
    )

    payload = build_knowledge_graph_health_status(state)

    assert payload["status"] == "ready"
    assert payload["neo4j_store_ready"] is True
    assert payload["entity_consumer_running"] is True
    assert payload["graph_updater_running"] is True


def test_build_knowledge_graph_health_status_degraded_when_updater_stops() -> None:
    state = SimpleNamespace(
        knowledge_graph_configured=True,
        neo4j_store=object(),
        entity_consumer_task=_TaskStub(done=False),
        graph_updater_task=_TaskStub(done=True),
    )

    payload = build_knowledge_graph_health_status(state)

    assert payload["status"] == "degraded"
    assert payload["entity_consumer_running"] is True
    assert payload["graph_updater_running"] is False