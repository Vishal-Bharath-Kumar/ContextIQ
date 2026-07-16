"""ParallelConnectorDispatcher — concurrent fetch across all active connectors.

TASK-US007-01: retrieval_agent node with asyncio.gather parallel dispatch.
TASK-US007-05: OTel concurrent span instrumentation for parallel connector calls.

Dispatches all connector ``fetch()`` calls concurrently.  A single connector
failure does **not** cancel the rest; failures are captured in
``FetchAllResult.failed_sources`` and the caller receives all chunks from
successful connectors.
"""
from __future__ import annotations

import asyncio
import logging
import time

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from src.agents.retrieval.connector_circuit_breaker import (
    ConnectorCircuitBreakerRegistry,
    ConnectorCircuitOpenError,
    async_call_with_breaker,
)
from src.agents.retrieval.metrics import (
    connector_failure_count,
    connector_fetch_duration,
)
from src.agents.retrieval.timeout_config import get_connector_timeout
from src.agents.retrieval.token_truncator import truncate_to_budget
from src.connector_sdk.base import BaseConnector
from src.connector_sdk.registry import ConnectorRegistry
from src.connector_sdk.schemas.query import ConnectorQuery

_logger = logging.getLogger(__name__)


# Re-export ConnectorCircuitOpenError so callers only need to import from this module
__all__ = [
    "ConnectorCircuitOpenError",
    "ConnectorTimeoutError",
    "ContextChunk",
    "FetchAllResult",
    "FailedSource",
    "ParallelConnectorDispatcher",
]

# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class ConnectorTimeoutError(Exception):
    """Raised when a connector's ``fetch()`` exceeds its configured timeout."""

    def __init__(self, source_id: str, timeout_seconds: float) -> None:
        self.source_id = source_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Connector '{source_id}' timed out after {timeout_seconds}s"
        )


# ---------------------------------------------------------------------------
# Result schemas
# ---------------------------------------------------------------------------


class ContextChunk(BaseModel):
    """A single retrieved chunk of context from a connector."""

    chunk_id: str
    source_id: str
    content: str
    token_count: int
    score: float = 0.0
    metadata: dict[str, str] = {}  # noqa: RUF012  file_path, timestamp, author, url


class FailedSource(BaseModel):
    """Record of a connector that raised an exception during fetch."""

    source_id: str
    error_type: str
    message: str


class FetchAllResult(BaseModel):
    """Aggregated output of a parallel connector dispatch."""

    chunks: list[ContextChunk]
    failed_sources: list[FailedSource]


# ---------------------------------------------------------------------------
# Internal per-connector result
# ---------------------------------------------------------------------------


class _FetchResult(BaseModel):
    """Wrapper returned by ``_fetch_one`` before flattening into ContextChunks."""

    source_id: str
    chunks: list[ContextChunk]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class ParallelConnectorDispatcher:
    """Dispatch ``fetch()`` to all active connectors in a single ``asyncio.gather`` call.

    Args:
        connector_registry: Runtime registry of all active connectors.
        timeout_seconds:    Per-connector hard timeout; defaults to ``5.0`` s.
    """

    def __init__(
        self,
        connector_registry: ConnectorRegistry,
        timeout_seconds: float | None = None,
        breaker_registry: ConnectorCircuitBreakerRegistry | None = None,
    ) -> None:
        self.registry = connector_registry
        self._timeout_override = timeout_seconds
        self.breaker_registry: ConnectorCircuitBreakerRegistry = (
            breaker_registry if breaker_registry is not None else ConnectorCircuitBreakerRegistry()
        )

    def _get_timeout(self, source_id: str) -> float:
        """Return the effective per-connector timeout for *source_id*.

        If *timeout_seconds* was supplied at construction time it takes
        precedence over the per-source override table (useful for tests).
        Otherwise, :func:`get_connector_timeout` is used.
        """
        if self._timeout_override is not None:
            return self._timeout_override
        return get_connector_timeout(source_id)

    async def fetch_all(
        self,
        query: str,
        source_ids: list[str],
        token_budget_per_source: dict[str, int],
    ) -> FetchAllResult:
        """Fetch from all requested active sources concurrently.

        Args:
            query:                  Raw user query forwarded to every connector.
            source_ids:             Connector IDs requested by the intent plan.
            token_budget_per_source: Per-source token budget hints (may be empty).

        Returns:
            :class:`FetchAllResult` with a flat list of chunks from successful
            connectors and a list of :class:`FailedSource` records for failures.
        """
        # Resolve active connectors — skip unknown / disabled source IDs silently.
        # Connectors with an open circuit breaker are pre-failed without dispatch.
        dispatchable: list[tuple[str, BaseConnector]] = []
        pre_failed: list[FailedSource] = []

        for src in source_ids:
            connector = self.registry.get(src)
            if connector is None:
                continue  # not registered — silently skip (health-check excluded it)

            if self.breaker_registry.is_open(src):
                pre_failed.append(
                    FailedSource(
                        source_id=src,
                        error_type="ConnectorCircuitOpenError",
                        message=f"Circuit breaker open for '{src}' — skipping dispatch",
                    )
                )
                connector_failure_count.labels(
                    connector_id=src, failure_type="circuit_open"
                ).inc()
                _logger.warning(
                    "connector_circuit_open_skip",
                    extra={"source_id": src},
                )
                continue

            dispatchable.append((src, connector))

        tasks = [
            self._fetch_one(
                source_id=src,
                connector=connector,
                query=query,
                token_budget=token_budget_per_source.get(src),
            )
            for src, connector in dispatchable
        ]

        # return_exceptions=True — a failing task returns the exception, not raises it.
        raw_results: list[_FetchResult | BaseException] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        chunks: list[ContextChunk] = []
        failed_sources: list[FailedSource] = list(pre_failed)

        for (src, _connector), result in zip(dispatchable, raw_results, strict=True):
            if isinstance(result, BaseException):
                _logger.warning(
                    "connector_fetch_failed",
                    extra={
                        "source_id": src,
                        "error_type": type(result).__name__,
                        "error_message": str(result),
                    },
                )
                failed_sources.append(
                    FailedSource(
                        source_id=src,
                        error_type=type(result).__name__,
                        message=str(result),
                    )
                )
            else:
                chunks.extend(result.chunks)

        return FetchAllResult(chunks=chunks, failed_sources=failed_sources)

    async def _fetch_one(
        self,
        source_id: str,
        connector: BaseConnector,
        query: str,
        token_budget: int | None,
    ) -> _FetchResult:
        """Fetch from a single connector with a hard timeout.

        Args:
            source_id:    Registry key identifying the connector.
            connector:    Active ``BaseConnector`` instance.
            query:        User query string.
            token_budget: Optional token budget hint for this source.

        Returns:
            :class:`_FetchResult` containing the source_id and converted chunks.

        Raises:
            ConnectorTimeoutError: when the connector exceeds its configured timeout.
            Any exception raised by the connector's ``fetch()`` method.
        """
        connector_type = source_id.split(":")[0]
        tracer = trace.get_tracer("contextiq.retrieval")

        with tracer.start_as_current_span(
            f"connector.fetch.{connector_type}",
            kind=trace.SpanKind.CLIENT,
        ) as span:
            span.set_attribute("connector.source_id", source_id)
            span.set_attribute("connector.type", connector_type)
            span.set_attribute("connector.token_budget", token_budget or 0)

            filters: dict[str, str] = {}
            if token_budget is not None:
                filters["token_budget"] = str(token_budget)

            connector_query = ConnectorQuery(query=query, filters=filters)
            timeout = self._get_timeout(source_id)
            t_start = time.monotonic()

            breaker = self.breaker_registry.get_or_create(source_id)

            async def _timed_fetch() -> list:  # type: ignore[type-arg]
                return await asyncio.wait_for(
                    connector.fetch(connector_query),
                    timeout=timeout,
                )

            try:
                raw_results = await async_call_with_breaker(
                    breaker=breaker,
                    source_id=source_id,
                    coro_factory=_timed_fetch,
                )
                elapsed_ms = int((time.monotonic() - t_start) * 1000)
                connector_fetch_duration.labels(
                    connector_id=source_id, status="success"
                ).observe(time.monotonic() - t_start)
                chunks = [
                    ContextChunk(
                        chunk_id=f"{source_id}:{result.source_id}",
                        source_id=source_id,
                        content=result.content,
                        token_count=max(1, len(result.content) // 4),
                        score=0.0,
                        metadata={
                            "source_url": result.metadata.source_url or "",
                            "author": result.metadata.author or "",
                            "last_modified": (
                                result.metadata.last_modified.isoformat()
                                if result.metadata.last_modified
                                else ""
                            ),
                            **result.metadata.extra,
                        },
                    )
                    for result in raw_results
                ]
                if token_budget is not None:
                    kept = truncate_to_budget(
                        [c.content for c in chunks], token_budget
                    )
                    chunks = chunks[: len(kept)]
                span.set_attribute("connector.chunks_returned", len(chunks))
                span.set_attribute("connector.duration_ms", elapsed_ms)
                span.set_status(StatusCode.OK)
                return _FetchResult(source_id=source_id, chunks=chunks)

            except ConnectorCircuitOpenError:
                span.set_status(StatusCode.ERROR, "circuit_open")
                span.set_attribute("connector.circuit_open", True)
                raise

            except asyncio.TimeoutError:
                connector_fetch_duration.labels(
                    connector_id=source_id, status="timeout"
                ).observe(time.monotonic() - t_start)
                connector_failure_count.labels(
                    connector_id=source_id, failure_type="timeout"
                ).inc()
                span.set_status(StatusCode.ERROR, "timeout")
                span.set_attribute("connector.timed_out", True)
                raise ConnectorTimeoutError(
                    source_id=source_id,
                    timeout_seconds=timeout,
                )

            except Exception as exc:
                connector_fetch_duration.labels(
                    connector_id=source_id, status="error"
                ).observe(time.monotonic() - t_start)
                connector_failure_count.labels(
                    connector_id=source_id, failure_type="error"
                ).inc()
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                raise
