"""Retrieval sub-package — parallel connector dispatch and result schemas."""

from src.agents.retrieval.aggregator import (
    AggregatedContext,
    ContextAggregator,
    DegradedSource,
)
from src.agents.retrieval.connector_loader import (
    CONNECTOR_CLASS_MAP,
    ConnectorLoader,
    health_check_loop,
)
from src.agents.retrieval.connector_registry import (
    ConnectorNotFoundError,
    ConnectorRegistry,
)
from src.agents.retrieval.parallel_dispatcher import (
    ConnectorTimeoutError,
    ContextChunk,
    FailedSource,
    FetchAllResult,
    ParallelConnectorDispatcher,
)
from src.agents.retrieval.timeout_config import get_connector_timeout

__all__ = [
    "AggregatedContext",
    "CONNECTOR_CLASS_MAP",
    "ConnectorLoader",
    "ConnectorNotFoundError",
    "ConnectorRegistry",
    "ConnectorTimeoutError",
    "ContextAggregator",
    "ContextChunk",
    "DegradedSource",
    "FailedSource",
    "FetchAllResult",
    "ParallelConnectorDispatcher",
    "get_connector_timeout",
    "health_check_loop",
]
