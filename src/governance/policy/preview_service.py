"""PolicyPreviewService — simulate a draft Rego policy against recent traces.

Implements AC-3: pushes the draft body to OPA under a temporary policy name,
evaluates the last 100 execution traces, then deletes the temporary policy.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.trace.models import TraceRecord
from src.governance.policy.schemas import PolicyPreviewRequest, PolicyPreviewResult

logger = logging.getLogger(__name__)

_PREVIEW_TRACE_LIMIT = 100
_TEMP_POLICY_PREFIX = "__preview__"


class PolicyPreviewService:
    """
    Simulates the effect of a draft Rego policy against the last N execution
    traces by pushing it to OPA under a temporary policy name, evaluating each
    trace's input, then deleting the temporary policy.
    """

    def __init__(
        self,
        session: AsyncSession,
        opa_client: httpx.AsyncClient,
        opa_base: str,
    ) -> None:
        self._session = session
        self._opa = opa_client
        self._opa_base = opa_base.rstrip("/")

    async def preview(
        self,
        policy_id: uuid.UUID,
        request: PolicyPreviewRequest,
    ) -> PolicyPreviewResult:
        traces = await self._load_recent_traces()
        temp_name = f"{_TEMP_POLICY_PREFIX}{policy_id.hex}"

        await self._push_temp_policy(temp_name, request.rego_body)
        try:
            results = await self._evaluate_traces(temp_name, traces)
        finally:
            await self._delete_temp_policy(temp_name)

        allow = sum(1 for r in results if r)
        deny = len(results) - allow
        n = len(results) or 1  # guard division-by-zero when no traces exist

        return PolicyPreviewResult(
            evaluated_count=len(results),
            allow_count=allow,
            deny_count=deny,
            allow_pct=round(allow / n * 100, 1),
            deny_pct=round(deny / n * 100, 1),
            affected_request_ids=[
                str(traces[i]["request_id"])
                for i, r in enumerate(results)
                if not r
            ],
        )

    async def _load_recent_traces(self) -> list[dict[str, Any]]:
        """Load the last 100 execution trace rows as OPA input dicts."""
        rows = (
            await self._session.execute(
                select(TraceRecord)
                .order_by(desc(TraceRecord.timestamp))
                .limit(_PREVIEW_TRACE_LIMIT)
            )
        ).scalars().all()

        return [
            {
                "request_id": str(row.request_id),
                "user_id": row.user_id,
                "tenant_id": row.tenant_id,
                "intent_type": row.intent,
                "chunk_id": None,  # not stored at trace level; OPA policy must handle None
            }
            for row in rows
        ]

    async def _push_temp_policy(self, name: str, rego_body: str) -> None:
        resp = await self._opa.put(
            f"{self._opa_base}/v1/policies/{name}",
            content=rego_body.encode(),
            headers={"Content-Type": "text/plain"},
        )
        resp.raise_for_status()

    async def _delete_temp_policy(self, name: str) -> None:
        try:
            await self._opa.delete(f"{self._opa_base}/v1/policies/{name}")
        except Exception:
            logger.warning(
                "Failed to clean up temporary preview policy %s", name
            )

    async def _evaluate_traces(
        self,
        policy_name: str,
        traces: list[dict[str, Any]],
    ) -> list[bool]:
        """Evaluate each trace against the temporary policy; returns allow booleans."""
        results: list[bool] = []
        for trace in traces:
            try:
                resp = await self._opa.post(
                    f"{self._opa_base}/v1/data/{policy_name}/allow",
                    json={"input": trace},
                )
                allowed = resp.json().get("result", False) is True
            except Exception:
                allowed = False  # treat OPA call failure as deny
            results.append(allowed)
        return results
