"""FastAPI application factory for the ContextIQ Agent Worker service.

TASK-US005-02: Implement ``POST /v1/execute`` Entrypoint and Initial State Hydration.
TASK-US005-03: Wire LangGraph AsyncRedisSaver Checkpointer for State Persistence.
TASK-US005-04: Initialise AIOKafkaProducer for state-transition event publishing.

Entry point
-----------
::

    python -m src.agent_worker.main

or via uvicorn::

    uvicorn src.agent_worker.main:app --host 0.0.0.0 --port 8001

Startup sequence
----------------
1. Initialise the ``TTLRedisSaver`` checkpointer (raises ``RuntimeError`` on
   connection failure so the pod fails fast rather than silently degrading).
2. Start the ``AIOKafkaProducer`` for state-transition event publishing.
3. Build and compile the LangGraph graph with both the checkpointer and the
   ``StateEventPublisher`` injected.
4. Store the compiled graph via ``set_graph`` so the ``/v1/execute`` router
   dependency can inject it.
5. Register the execute router.
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI

from src.agent_worker.routers.execute import router as execute_router
from src.agent_worker.routers.execute import set_graph
from src.agents.checkpointer import get_redis_checkpointer
from src.agents.config import settings
from src.agents.events.state_event_publisher import StateEventPublisher
from src.agents.graph import build_graph
from src.agents.nodes.retrieval import set_connector_registry
from src.agents.source_selector import FALLBACK_SOURCES, _validate_source_map
from src.audit.trace.object_store import TraceObjectStore
from src.audit.trace.writer_node import set_trace_object_store, set_trace_session_factory
from src.connector_sdk.registry import ConnectorRegistry
from src.data.database import primary_session_factory
from src.events.producer import _sasl_kwargs
from src.governance.opa.health import default_opa_health_status, opa_health_status
from src.governance.nodes.opa_filter_node import set_opa_client
from src.governance.opa.bundle_loader import BundleNotReadyError, PolicyBundleLoader
from src.governance.opa.client import OPAClient
from src.knowledge_graph.extraction.extractor import ExtractionSettings
from src.knowledge_graph.inference.edge_inference_engine import EdgeInferenceSettings
from src.knowledge_graph.traversal.entity_linker import EntityLinkerSettings
from src.llm.ollama_verify import verify_ollama_models_available

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialise the Redis checkpointer, Kafka producer, and LangGraph graph."""
    logger.info("agent_worker: initialising Redis checkpointer")
    checkpointer = await get_redis_checkpointer()
    app.state.checkpointer = checkpointer

    app.state.ollama_verification = await verify_ollama_models_available(
        [
            settings.llm_model_id,
            EntityLinkerSettings().model_id,
            ExtractionSettings().model_id,
            EdgeInferenceSettings().model_id,
        ]
    )
    app.state.opa_health = default_opa_health_status()

    logger.info("agent_worker: loading connector registry")
    connector_registry = ConnectorRegistry()
    await connector_registry.load()
    set_connector_registry(connector_registry)
    app.state.connector_registry = connector_registry

    try:
        trace_store = TraceObjectStore()
        set_trace_object_store(trace_store)
        set_trace_session_factory(primary_session_factory())
        app.state.trace_object_store = trace_store
    except Exception:
        logger.warning("agent_worker: trace writer dependencies unavailable", exc_info=True)

    if os.environ.get("OPA_BASE_URL"):
        bundle_loader = PolicyBundleLoader()
        try:
            app.state.bundle_info = await bundle_loader.verify()
            app.state.opa_client = OPAClient()
            set_opa_client(app.state.opa_client)
            app.state.opa_health = opa_health_status(
                configured=True,
                bundle_ready=True,
                degraded=False,
                bundle_version=app.state.bundle_info.version,
            )
        except BundleNotReadyError:
            if settings.allow_degraded_opa_startup:
                logger.warning(
                    "agent_worker: OPA bundle not ready — continuing startup in degraded mode"
                )
                app.state.bundle_info = None
                app.state.opa_client = None
                app.state.opa_health = opa_health_status(
                    configured=True,
                    bundle_ready=False,
                    degraded=True,
                    error="OPA bundle not ready",
                )
            else:
                app.state.opa_health = opa_health_status(
                    configured=True,
                    bundle_ready=False,
                    degraded=False,
                    error="OPA bundle not ready",
                )
                logger.critical("agent_worker: OPA bundle not ready — refusing to start")
                raise

    # Validate SOURCE_MAP against the full set of known connector IDs (AIR-006).
    _validate_source_map(set(FALLBACK_SOURCES))

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    logger.info("agent_worker: starting Kafka producer (bootstrap=%s)", bootstrap_servers)
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers, **_sasl_kwargs())
    await producer.start()
    app.state.kafka_producer = producer
    state_publisher = StateEventPublisher(producer)

    logger.info("agent_worker: compiling LangGraph graph")
    graph = build_graph(checkpointer=checkpointer, publisher=state_publisher)
    set_graph(graph)
    logger.info("agent_worker: graph compiled — ready to serve")
    yield
    logger.info("agent_worker: shutdown — stopping Kafka producer")
    await producer.stop()
    logger.info("agent_worker: shutdown — closing Redis checkpointer")
    await checkpointer.aclose()
    logger.info("agent_worker: shutdown complete")


def create_app() -> FastAPI:
    """Create and return the Agent Worker FastAPI application."""
    application = FastAPI(
        title="ContextIQ Agent Worker",
        description="Executes MCP tool calls via the LangGraph multi-agent pipeline.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(execute_router)
    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "src.agent_worker.main:app",
        host="0.0.0.0",  # noqa: S104
        port=8001,
        log_level="info",
    )
