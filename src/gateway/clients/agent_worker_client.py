"""
Async HTTP client for the Agent Worker service.

TASK-US003-02: Agent Worker HTTP Client and Output Schema Validation.
TASK-US003-05: End-to-End Correlation ID Tracing and SLA Monitoring.

Wraps the ``POST /v1/execute`` endpoint of the Agent Worker Kubernetes service.
All I/O is non-blocking (``httpx.AsyncClient``).  Key responsibilities:

- Inject W3C ``traceparent`` / ``tracestate`` propagation headers via
  ``opentelemetry.propagate.inject`` so Agent Worker spans appear as children
  of the gateway's ``mcp.tools.call`` span in Jaeger.
- Inject correlation headers (``X-Request-ID``, ``X-Trace-ID``).
- Attach a short-lived Vault-issued Bearer token (cached for 4 minutes).
- Enforce a 5-second hard timeout (SLA buffer above the p95 < 3 s target).
- Deserialise the response into :class:`ToolCallOutput`.
- Raise :class:`~mcp.shared.exceptions.McpError` on timeout or HTTP 5xx.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from src.gateway.schemas.call_types import (
    AgentWorkerResponse,
    ToolCallDispatch,
    ToolCallOutput,
)

logger = logging.getLogger(__name__)

_EXECUTE_PATH = "/v1/execute"
_DEFAULT_BASE_URL = "http://contextiq-agent-worker.contextiq-agents.svc.cluster.local"
_DEFAULT_TIMEOUT_SECONDS: float = 5.0
_TOKEN_TTL_SECONDS: float = 240.0  # 4 minutes — comfortably under 5-minute Vault expiry

# Callable type for the injectable token-fetch function.
_TokenFetcher = Callable[[], Coroutine[Any, Any, str]]


class _ServiceTokenCache:
    """Thread-safe, time-bounded cache for a single service Bearer token.

    Parameters
    ----------
    ttl_seconds:
        How long (in seconds) to retain the cached token.  Default: 240 s (4 min).
    """

    def __init__(self, ttl_seconds: float = _TOKEN_TTL_SECONDS) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._ttl = ttl_seconds
        self._lock: asyncio.Lock | None = None  # Created lazily to avoid loop binding issues.

    @property
    def _async_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get(self, fetch: _TokenFetcher) -> str:
        """Return the cached token or invoke *fetch* to refresh it."""
        if self._token is not None and time.monotonic() < self._expires_at:
            return self._token
        async with self._async_lock:
            # Double-checked locking: another coroutine may have refreshed it.
            if self._token is not None and time.monotonic() < self._expires_at:
                return self._token
            self._token = await fetch()
            self._expires_at = time.monotonic() + self._ttl
            return self._token


class AgentWorkerClient:
    """Async HTTP client for the Agent Worker ``POST /v1/execute`` endpoint.

    Parameters
    ----------
    base_url:
        Base URL of the Agent Worker service.  Defaults to the in-cluster
        Kubernetes service DNS name; override via ``CONTEXTIQ_AGENT_WORKER_BASE_URL``.
    timeout_seconds:
        Hard request timeout in seconds.  Defaults to 5.0 (SLA buffer).
    vault_addr:
        Vault server address used to obtain the service Bearer token.
        Defaults to ``http://vault.vault.svc.cluster.local:8200``.
    token_fetcher:
        Optional injectable async callable ``() -> str`` that returns a Bearer
        token string.  Inject a mock in tests to avoid real Vault calls.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        vault_addr: str = "http://vault.vault.svc.cluster.local:8200",
        token_fetcher: _TokenFetcher | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._vault_addr = vault_addr.rstrip("/")
        self._token_cache = _ServiceTokenCache()
        self._token_fetcher: _TokenFetcher = token_fetcher if token_fetcher is not None else self._fetch_vault_token

    async def execute(self, dispatch: ToolCallDispatch) -> ToolCallOutput:
        """Forward *dispatch* to the Agent Worker and return the validated output.

        Raises
        ------
        McpError(INTERNAL_ERROR)
            On request timeout or Agent Worker HTTP error.
        """
        url = f"{self._base_url}{_EXECUTE_PATH}"
        token = await self._token_cache.get(self._token_fetcher)
        headers: dict[str, str] = {
            "X-Request-ID": dispatch.request_id,
            "X-Trace-ID": dispatch.trace_id,
            "Authorization": f"Bearer {token}",
        }

        # TASK-US003-05: Inject W3C traceparent / tracestate so Agent Worker
        # spans become children of the current gateway span in Jaeger.
        try:
            from opentelemetry.propagate import inject as _otel_inject

            _otel_inject(headers)
        except Exception:  # noqa: BLE001
            pass  # OTel absent or inactive — proceed without propagation header
        logger.debug(
            "agent_worker: dispatching tool=%s request_id=%s",
            dispatch.tool_name,
            dispatch.request_id,
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=dispatch.model_dump(), headers=headers)
                resp.raise_for_status()
        except httpx.TimeoutException as exc:
            timeout_ms = int(self._timeout * 1000)
            logger.error(
                "agent_worker: timeout after %d ms for tool=%s request_id=%s",
                timeout_ms,
                dispatch.tool_name,
                dispatch.request_id,
            )
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR,
                    message="Agent pipeline timed out",
                    data={"timeout_ms": timeout_ms},
                )
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logger.error(
                "agent_worker: HTTP %d for tool=%s request_id=%s",
                status_code,
                dispatch.tool_name,
                dispatch.request_id,
            )
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR,
                    message=f"Agent Worker returned {status_code}",
                )
            ) from exc

        worker_response = AgentWorkerResponse.model_validate(resp.json())
        if worker_response.output is None:
            raise McpError(
                ErrorData(
                    code=INTERNAL_ERROR,
                    message="Agent Worker returned empty output",
                )
            )
        return worker_response.output

    async def _fetch_vault_token(self) -> str:
        """Request a short-lived JWT from Vault PKI and return it as a string.

        Uses the ``pki/issue/contextiq-gateway`` endpoint.  The returned
        certificate's ``certificate`` field is used as the Bearer token value.

        Note: this method makes a real network call; inject *token_fetcher* in
        tests to avoid Vault dependency.
        """
        vault_url = f"{self._vault_addr}/v1/pki/issue/contextiq-gateway"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(vault_url, json={"common_name": "contextiq-gateway"})
            resp.raise_for_status()
        data = resp.json()
        return data["data"]["certificate"]
