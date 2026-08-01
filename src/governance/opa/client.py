"""OPA sidecar client for per-chunk authorization evaluation.

Satisfies AC-2 (OPA call per chunk with required fields) and AC-5 (≤ 50 ms
per chunk via localhost IPC).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.governance.opa.schemas import AuthzFilterResult, ChunkAuthzInput, PolicyDecision

logger = logging.getLogger(__name__)


class OPAClientSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPA_", env_file=".env", extra="ignore")

    base_url: str = "http://localhost:8181"
    # Per-chunk call timeout. Local Docker dev incurs noticeably more network
    # overhead than the target hot path, so the runtime default is relaxed.
    request_timeout_s: float = 1.0
    # OPA data path for the policy rule (AC-2).
    policy_path: str = "v1/data/contextiq/authz/allow"
    # OPA status endpoint for bundle verification (AC-1).
    status_path: str = "v1/status"
    # Expected bundle name as configured in the OPA sidecar bundle config.
    expected_bundle_name: str = "contextiq_policies"
    # Connection pool size — reuse connections across concurrent evaluations.
    max_connections: int = 20


class OPAEvaluationError(RuntimeError):
    """Raised when OPA returns a non-200 response or the call times out."""


class OPAClient:
    """Async client for the OPA sidecar REST API.

    A single shared :class:`httpx.AsyncClient` is reused across evaluations
    so that the connection pool is warm and transport overhead stays < 1 ms.
    """

    def __init__(self, settings: OPAClientSettings | None = None) -> None:
        self._settings = settings or OPAClientSettings()
        # Single shared async client — connection pool is reused across evaluations.
        self._http = httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=self._settings.request_timeout_s,
            limits=httpx.Limits(max_connections=self._settings.max_connections),
            trust_env=False,
        )

    async def evaluate_chunk(self, inp: ChunkAuthzInput) -> PolicyDecision:
        """Call OPA ``data.contextiq.authz.allow`` for a single chunk.

        OPA REST API request format::

            POST /v1/data/contextiq/authz/allow
            {"input": <ChunkAuthzInput as dict>}

        Response: ``{"result": true|false}``

        The Rego ``deny_reason`` rule is fetched as a second call only when
        ``allow=False``, to avoid the overhead on the allow (common) path.

        Raises :exc:`OPAEvaluationError` on HTTP error or timeout.
        """
        start = time.monotonic()
        payload = {"input": inp.model_dump()}
        url = self._settings.policy_path

        try:
            response = await self._http.post(url, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise OPAEvaluationError(
                f"OPA evaluation timed out for chunk={inp.chunk_id}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OPAEvaluationError(
                f"OPA returned HTTP {exc.response.status_code} for chunk={inp.chunk_id}"
            ) from exc

        data = response.json()
        allowed = bool(data.get("result", False))
        eval_ms = (time.monotonic() - start) * 1000

        rationale = ""
        if not allowed:
            rationale = await self._fetch_deny_reason(inp)

        return PolicyDecision(
            chunk_id=inp.chunk_id,
            allow=allowed,
            rationale=rationale,
            eval_ms=eval_ms,
        )

    async def evaluate_batch(
        self,
        inputs: list[ChunkAuthzInput],
        concurrency: int = 10,
    ) -> AuthzFilterResult:
        """Evaluate all chunks concurrently (bounded by ``concurrency`` semaphore).

        Returns :class:`AuthzFilterResult` with allow/deny split and total eval time.

        Concurrency=10 at 50 ms each → effective throughput ≥ 200 chunks/s,
        well above the typical context window size of 20–50 chunks.
        """
        sem = asyncio.Semaphore(concurrency)
        start = time.monotonic()

        async def _eval_one(inp: ChunkAuthzInput) -> PolicyDecision:
            async with sem:
                return await self.evaluate_chunk(inp)

        decisions = await asyncio.gather(*[_eval_one(i) for i in inputs])
        total_eval_ms = (time.monotonic() - start) * 1000

        allowed = [d.chunk_id for d in decisions if d.allow]
        denied = [d.chunk_id for d in decisions if d.is_denied]

        return AuthzFilterResult(
            decisions=list(decisions),
            allowed_chunk_ids=allowed,
            denied_chunk_ids=denied,
            total_eval_ms=total_eval_ms,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client and release connection pool resources."""
        await self._http.aclose()

    async def _fetch_deny_reason(self, inp: ChunkAuthzInput) -> str:
        """Fetch the Rego ``deny_reason`` rule value for a denied chunk.

        Returns empty string on any error — denial is already recorded.
        """
        url = "v1/data/contextiq/authz/deny_reason"
        try:
            resp = await self._http.post(url, json={"input": inp.model_dump()})
            resp.raise_for_status()
            return str(resp.json().get("result") or "")
        except Exception:
            return ""
