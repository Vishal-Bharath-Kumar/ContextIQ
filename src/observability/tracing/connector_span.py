"""Connector fetch() span decorator — TASK-US038-04.

Wraps any connector ``fetch()`` method in a child OTel span parented to the
root span stored in ``self._otel_ctx`` (AC-3).  Sets the required span
attributes ``connector_id`` and ``source_id`` from the connector instance
(AC-4).

Usage::

    class MyConnector(BaseConnector):
        connector_id   = "my_connector"
        source_id      = "my-source-uuid"
        connector_type = "rest"

        @connector_span
        async def fetch(self, query: ConnectorQuery) -> list[ConnectorResult]: ...

Applied automatically to all ``BaseConnector`` subclasses that define
``fetch()`` via ``BaseConnector.__init_subclass__``.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any  # used only for class-attribute annotations

from opentelemetry import context as otel_context
from opentelemetry import trace

from src.observability.tracing.root_span import RootSpanContext

logger = logging.getLogger(__name__)
_TRACER = trace.get_tracer(__name__)


def connector_span(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Decorator for connector ``fetch()`` methods (AC-3).

    Expects ``self`` to have:
    - ``self.connector_id: str``  — unique connector identifier
    - ``self.source_id: str``     — knowledge source UUID

    The span context is retrieved from ``self._otel_ctx`` if the connector
    stores it during request setup, or by scanning positional / keyword args
    for a dict containing ``_otel_ctx``.

    When no :class:`~src.observability.tracing.root_span.RootSpanContext` is
    found the decorator is a transparent pass-through (safe in unit tests that
    run without OTel).
    """

    @functools.wraps(fn)
    async def wrapper(self: object, *args: object, **kwargs: object) -> object:
        rsc: RootSpanContext | None = getattr(self, "_otel_ctx", None) or _extract_ctx_from_args(
            args, kwargs
        )

        connector_id: str = getattr(self, "connector_id", "unknown")
        source_id: str = getattr(self, "source_id", "unknown")
        span_name: str = f"connector.{connector_id}.fetch"

        if rsc is None:
            return await fn(self, *args, **kwargs)

        token = otel_context.attach(trace.set_span_in_context(rsc.span))
        try:
            with _TRACER.start_as_current_span(
                span_name,
                kind=trace.SpanKind.CLIENT,
            ) as span:
                # AC-3, AC-4: required connector span attributes
                span.set_attribute("connector_id", connector_id)
                span.set_attribute("source_id", source_id)
                span.set_attribute("connector.type", getattr(self, "connector_type", "unknown"))
                span.set_attribute("request_id", str(getattr(self, "_request_id", "")))
                try:
                    result = await fn(self, *args, **kwargs)
                    span.set_attribute("connector.fetch_ok", True)
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(trace.StatusCode.ERROR, description=str(exc))
                    raise
        finally:
            otel_context.detach(token)

    return wrapper


def _extract_ctx_from_args(
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> RootSpanContext | None:
    """Scan positional / keyword args for a dict containing ``_otel_ctx``."""
    for arg in args:
        if isinstance(arg, dict) and "_otel_ctx" in arg:
            rsc = arg["_otel_ctx"]
            if isinstance(rsc, RootSpanContext):
                return rsc
    for val in kwargs.values():
        if isinstance(val, dict) and "_otel_ctx" in val:
            rsc = val["_otel_ctx"]
            if isinstance(rsc, RootSpanContext):
                return rsc
    return None
