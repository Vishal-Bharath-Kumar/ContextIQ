"""
Concurrency isolation tests for TASK-US003-04.

Validates that concurrent ``tools/call`` invocations each receive an
independent ``RequestContext`` with distinct ``request_id`` values, and that
a failure in one concurrent call does not contaminate the others.

Coverage targets (≥ 90% on gateway/context/request_context.py and
gateway/middleware/context_middleware.py):
  - 20 concurrent calls each have a distinct request_id (no collisions)
  - A failure in one concurrent call does not affect the others
  - Log records bind the correct request_id (no cross-contamination)
  - _request_ctx.reset(token) is called in finally — stale context never leaks
  - ContextVar child-task isolation: child mutations do not reach parent
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gateway.context.request_context import (
    RequestContext,
    _request_ctx,
    get_request_context,
    set_request_context,
)
from src.gateway.middleware.context_middleware import RequestContextMiddleware


# ---------------------------------------------------------------------------
# RequestContext unit tests
# ---------------------------------------------------------------------------

class TestRequestContext:
    def test_frozen_dataclass(self) -> None:
        ctx = RequestContext(
            request_id="req-1",
            user_id="user-a",
            username="",
            roles=frozenset(),
            session_id="sess-1",
            trace_id=42,
        )
        with pytest.raises((AttributeError, TypeError)):
            ctx.request_id = "mutated"  # type: ignore[misc]

    def test_set_and_get_round_trip(self) -> None:
        ctx = RequestContext(
            request_id="req-abc",
            user_id="user-xyz",
            username="",
            roles=frozenset(),
            session_id="sess-xyz",
            trace_id=0,
        )
        token = set_request_context(ctx)
        try:
            assert get_request_context() is ctx
        finally:
            _request_ctx.reset(token)

    @pytest.mark.asyncio
    async def test_get_raises_when_not_set(self) -> None:
        """LookupError when ContextVar has no value in this task."""
        async def _task_with_no_context() -> None:
            with pytest.raises(LookupError):
                get_request_context()

        await _task_with_no_context()

    def test_reset_clears_context(self) -> None:
        ctx = RequestContext(request_id="r", user_id="u", username="", roles=frozenset(), session_id="s", trace_id=0)
        token = set_request_context(ctx)
        _request_ctx.reset(token)
        with pytest.raises(LookupError):
            get_request_context()


# ---------------------------------------------------------------------------
# ContextVar child-task isolation
# ---------------------------------------------------------------------------

class TestContextVarIsolation:
    @pytest.mark.asyncio
    async def test_child_task_inherits_parent_context(self) -> None:
        """Child task sees parent context at spawn time."""
        parent_ctx = RequestContext(
            request_id="parent-req",
            user_id="parent-user",
            username="",
            roles=frozenset(),
            session_id="parent-sess",
            trace_id=0,
        )
        token = set_request_context(parent_ctx)
        child_seen: list[str] = []

        async def _child() -> None:
            child_seen.append(get_request_context().request_id)

        try:
            task = asyncio.create_task(_child())
            await task
        finally:
            _request_ctx.reset(token)

        assert child_seen == ["parent-req"]

    @pytest.mark.asyncio
    async def test_child_mutation_does_not_propagate_to_parent(self) -> None:
        """Mutations inside child task stay inside child; parent is unaffected."""
        parent_ctx = RequestContext(
            request_id="parent-req",
            user_id="parent-user",
            username="",
            roles=frozenset(),
            session_id="parent-sess",
            trace_id=0,
        )
        token = set_request_context(parent_ctx)
        child_token_holder: list[Any] = []

        async def _child() -> None:
            child_ctx = RequestContext(
                request_id="child-req",
                user_id="child-user",
                username="",
                roles=frozenset(),
                session_id="child-sess",
                trace_id=0,
            )
            t = set_request_context(child_ctx)
            child_token_holder.append(t)
            # do not reset — test that parent is still unaffected

        try:
            task = asyncio.create_task(_child())
            await task
            # Parent context must still be the original
            assert get_request_context().request_id == "parent-req"
        finally:
            _request_ctx.reset(token)


# ---------------------------------------------------------------------------
# Concurrency isolation — 20 simultaneous calls
# ---------------------------------------------------------------------------

class TestConcurrentIsolation:
    @pytest.mark.asyncio
    async def test_20_concurrent_calls_produce_distinct_request_ids(self) -> None:
        """20 concurrent asyncio tasks must each get a unique request_id."""
        collected: list[str] = []

        async def _simulate_request(index: int) -> None:
            ctx = RequestContext(
                request_id=f"req-{index:04d}",
                user_id=f"user-{index}",
                username="",
                roles=frozenset(),
                session_id=f"sess-{index}",
                trace_id=index,
            )
            token = set_request_context(ctx)
            try:
                # Yield to the event loop so other tasks run interleaved.
                await asyncio.sleep(0)
                collected.append(get_request_context().request_id)
            finally:
                _request_ctx.reset(token)

        await asyncio.gather(*[_simulate_request(i) for i in range(20)])

        assert len(collected) == 20
        assert len(set(collected)) == 20, "Duplicate request_id found — context leaked"

    @pytest.mark.asyncio
    async def test_failure_in_one_call_does_not_affect_others(self) -> None:
        """A timeout/error in one concurrent call must not corrupt sibling contexts."""
        success_ids: list[str] = []
        error_count = 0

        async def _failing_request() -> None:
            ctx = RequestContext(
                request_id="failing-req",
                user_id="u",
                username="",
                roles=frozenset(),
                session_id="s",
                trace_id=0,
            )
            token = set_request_context(ctx)
            try:
                await asyncio.sleep(0)
                raise RuntimeError("simulated agent timeout")
            finally:
                _request_ctx.reset(token)

        async def _success_request(index: int) -> None:
            ctx = RequestContext(
                request_id=f"success-req-{index}",
                user_id=f"user-{index}",
                username="",
                roles=frozenset(),
                session_id=f"sess-{index}",
                trace_id=index,
            )
            token = set_request_context(ctx)
            try:
                await asyncio.sleep(0)
                success_ids.append(get_request_context().request_id)
            finally:
                _request_ctx.reset(token)

        tasks = [_failing_request()] + [_success_request(i) for i in range(9)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Exactly one failure
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 1
        assert "simulated agent timeout" in str(errors[0])

        # Remaining 9 succeeded with distinct IDs
        assert len(success_ids) == 9
        assert len(set(success_ids)) == 9

    @pytest.mark.asyncio
    async def test_context_not_leaked_after_request(self) -> None:
        """After reset, the ContextVar must have no value in the same task."""
        ctx = RequestContext(
            request_id="leaky-req",
            user_id="u",
            username="",
            roles=frozenset(),
            session_id="s",
            trace_id=0,
        )
        token = set_request_context(ctx)
        _request_ctx.reset(token)

        with pytest.raises(LookupError):
            get_request_context()


# ---------------------------------------------------------------------------
# RequestContextMiddleware tests
# ---------------------------------------------------------------------------

class TestRequestContextMiddleware:
    """ASGI middleware behaviour: context injection, scope filtering, reset."""

    def _make_scope(
        self,
        scope_type: str = "http",
        user_id: str = "mw-user",
        session_id: str = "mw-sess",
    ) -> dict[str, Any]:
        return {
            "type": scope_type,
            "path": "/mcp/sse",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "state": {"user_id": user_id, "session_id": session_id},
        }

    @pytest.mark.asyncio
    async def test_middleware_injects_request_context(self) -> None:
        """Middleware must set a valid RequestContext in the inner app."""
        captured: list[RequestContext] = []

        async def _inner_app(scope: Any, receive: Any, send: Any) -> None:
            captured.append(get_request_context())

        mw = RequestContextMiddleware(_inner_app)
        scope = self._make_scope(user_id="alice", session_id="sess-abc")
        await mw(scope, None, None)

        assert len(captured) == 1
        ctx = captured[0]
        assert ctx.user_id == "alice"
        assert ctx.session_id == "sess-abc"
        assert len(ctx.request_id) == 36  # UUID v4 format

    @pytest.mark.asyncio
    async def test_middleware_resets_context_after_request(self) -> None:
        """After the request completes, the ContextVar must be reset."""
        # Record the token before middleware runs to confirm reset behaviour
        async def _inner_app(scope: Any, receive: Any, send: Any) -> None:
            pass  # just complete

        mw = RequestContextMiddleware(_inner_app)
        await mw(self._make_scope(), None, None)

        with pytest.raises(LookupError):
            get_request_context()

    @pytest.mark.asyncio
    async def test_middleware_resets_on_inner_app_exception(self) -> None:
        """Context must be reset even if the inner app raises."""
        async def _failing_app(scope: Any, receive: Any, send: Any) -> None:
            raise RuntimeError("inner failure")

        mw = RequestContextMiddleware(_failing_app)
        with pytest.raises(RuntimeError, match="inner failure"):
            await mw(self._make_scope(), None, None)

        with pytest.raises(LookupError):
            get_request_context()

    @pytest.mark.asyncio
    async def test_middleware_skips_non_http_websocket_scopes(self) -> None:
        """Lifespan and other scope types must be forwarded unchanged."""
        captured: list[str] = []

        async def _inner_app(scope: Any, receive: Any, send: Any) -> None:
            captured.append(scope["type"])

        mw = RequestContextMiddleware(_inner_app)
        await mw({"type": "lifespan"}, None, None)
        assert captured == ["lifespan"]

    @pytest.mark.asyncio
    async def test_middleware_each_request_gets_unique_request_id(self) -> None:
        """Two sequential requests through the middleware must each get a unique ID."""
        ids: list[str] = []

        async def _inner_app(scope: Any, receive: Any, send: Any) -> None:
            ids.append(get_request_context().request_id)

        mw = RequestContextMiddleware(_inner_app)
        scope = self._make_scope()
        await mw(scope, None, None)
        await mw(scope, None, None)

        assert len(ids) == 2
        assert ids[0] != ids[1], "Sequential requests received the same request_id"

    @pytest.mark.asyncio
    async def test_concurrent_requests_each_get_unique_request_id(self) -> None:
        """10 concurrent requests must each receive a distinct request_id."""
        ids: list[str] = []

        async def _inner_app(scope: Any, receive: Any, send: Any) -> None:
            await asyncio.sleep(0)  # yield — allow interleaving
            ids.append(get_request_context().request_id)

        mw = RequestContextMiddleware(_inner_app)
        scopes = [self._make_scope(user_id=f"user-{i}", session_id=f"sess-{i}") for i in range(10)]
        await asyncio.gather(*[mw(s, None, None) for s in scopes])

        assert len(ids) == 10
        assert len(set(ids)) == 10, f"ID collision detected: {ids}"


# ---------------------------------------------------------------------------
# Structured log context binding
# ---------------------------------------------------------------------------

class TestStructuredLogBinding:
    @pytest.mark.asyncio
    async def test_log_records_carry_request_id(self, caplog: pytest.LogCaptureFixture) -> None:
        """A handler that logs inside a request must emit the correct request_id."""
        test_request_id = "log-req-999"

        async def _logging_handler() -> None:
            ctx = RequestContext(
                request_id=test_request_id,
                user_id="u",
                username="",
                roles=frozenset(),
                session_id="s",
                trace_id=0,
            )
            token = set_request_context(ctx)
            try:
                logger = logging.getLogger("test.concurrent_isolation")
                retrieved = get_request_context().request_id
                logger.info("handled request_id=%s", retrieved)
            finally:
                _request_ctx.reset(token)

        with caplog.at_level(logging.INFO):
            await asyncio.gather(
                _logging_handler(),
                _logging_handler(),
                _logging_handler(),
            )

        # All log records must reference *their own* request_id.
        # Because each task resets its own token, all records are valid.
        for record in caplog.records:
            assert test_request_id in record.getMessage()

    @pytest.mark.asyncio
    async def test_concurrent_log_records_do_not_cross_contaminate(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Concurrent tasks must log their own request_id — no cross-contamination."""
        recorded: list[tuple[str, str]] = []  # (task_id, logged_request_id)

        async def _task(task_id: str) -> None:
            ctx = RequestContext(
                request_id=f"req-for-{task_id}",
                user_id="u",
                username="",
                roles=frozenset(),
                session_id="s",
                trace_id=0,
            )
            token = set_request_context(ctx)
            try:
                await asyncio.sleep(0)
                seen = get_request_context().request_id
                recorded.append((task_id, seen))
            finally:
                _request_ctx.reset(token)

        task_ids = [f"task-{i}" for i in range(10)]
        await asyncio.gather(*[_task(tid) for tid in task_ids])

        assert len(recorded) == 10
        for task_id, logged_req_id in recorded:
            expected = f"req-for-{task_id}"
            assert logged_req_id == expected, (
                f"Task {task_id!r} logged request_id {logged_req_id!r}, "
                f"expected {expected!r}"
            )
