"""
Per-request execution context propagated via Python contextvars.

TASK-US003-04: Session Isolation for Concurrent Tool Calls.

Each asyncio task (i.e. each inbound ``tools/call`` invocation) automatically
receives an isolated copy of the context at task-spawn time.  Changes made
inside a child task do not propagate back to the parent, so concurrent calls
can never observe each other's ``RequestContext``.

Usage
-----
Middleware populates the context once per request::

    token = set_request_context(ctx)
    try:
        await app(scope, receive, send)
    finally:
        _request_ctx.reset(token)   # prevents stale context from leaking

Handlers read it without argument threading::

    ctx = get_request_context()
    logger.info("handling request", request_id=ctx.request_id)
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    """Immutable per-request execution context.

    Frozen so handlers can never accidentally mutate shared state — any
    change would require creating a new instance and re-setting the var.

    Attributes
    ----------
    request_id:
        UUID v4 string, unique per ``tools/call`` invocation.
    user_id:
        Authenticated user identifier extracted from the JWT ``sub`` claim.
    username:
        Human-readable identity from the JWT ``preferred_username`` claim.
        Empty string when the claim is absent.
    roles:
        Immutable set of platform roles merged from ``realm_access.roles``
        and ``resource_access.<client-id>.roles`` — TASK-US004-03.
    session_id:
        MCP session identifier (transport-level, e.g. SSE connection ID).
    trace_id:
        OpenTelemetry trace ID integer from the current span context.
        ``0`` when no active span is present (e.g. in unit tests).
    """

    request_id: str
    user_id: str
    username: str
    roles: frozenset[str]
    session_id: str
    trace_id: int


# Module-level ContextVar — isolated per asyncio task automatically.
# ``asyncio.gather`` / ``asyncio.create_task`` each copy the calling context
# at spawn time; mutations inside the child never propagate to the parent.
_request_ctx: ContextVar[RequestContext] = ContextVar("request_context")


def get_request_context() -> RequestContext:
    """Return the ``RequestContext`` bound to the current asyncio task.

    Raises
    ------
    LookupError
        If ``set_request_context`` was never called for this task.  This
        should not happen in production because the middleware always runs
        before handler code.
    """
    return _request_ctx.get()


def set_request_context(ctx: RequestContext) -> Token[RequestContext]:
    """Bind *ctx* to the current asyncio task and return a reset token.

    Always pair with ``_request_ctx.reset(token)`` in a ``finally`` block
    to prevent stale context from leaking to the next request that may reuse
    the same OS thread or event-loop slot.

    Parameters
    ----------
    ctx:
        The ``RequestContext`` to bind.

    Returns
    -------
    Token[RequestContext]
        Opaque token that must be passed to ``_request_ctx.reset()`` when
        the request finishes.
    """
    return _request_ctx.set(ctx)
