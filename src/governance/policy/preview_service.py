"""PolicyPreviewService — simulate a draft Rego policy against recent traces.

Implements AC-3: pushes the draft body to OPA under a temporary policy name,
evaluates the last 100 execution traces, then deletes the temporary policy.
"""
from __future__ import annotations

import logging
import re
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
        # Sanitize policy ID for OPA: only letters, digits, underscores allowed
        sanitized_id = re.sub(r'[^a-zA-Z0-9_]', '_', policy_id.hex)
        temp_name = f"{_TEMP_POLICY_PREFIX}{sanitized_id}"
        preview_package = f"preview.{temp_name}"

        await self._push_temp_policy(temp_name, preview_package, request.rego_body)
        try:
            results = await self._evaluate_traces(preview_package, traces)
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

    async def _push_temp_policy(self, name: str, preview_package: str, rego_body: str) -> None:
        # Rewrite package name to avoid conflicts with existing policies
        rewritten_body = self._rewrite_package_name(rego_body, preview_package)
        
        logger.info(
            "Pushing preview policy %s with package %s (original: %s chars, rewritten: %s chars)",
            name,
            preview_package,
            len(rego_body),
            len(rewritten_body),
        )
        
        resp = await self._opa.put(
            f"{self._opa_base}/v1/policies/{name}",
            content=rewritten_body.encode(),
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
        package_path: str,
        traces: list[dict[str, Any]],
    ) -> list[bool]:
        """Evaluate each trace against the temporary policy; returns allow booleans."""
        results: list[bool] = []
        # Convert package path to OPA data path (e.g., preview.__preview__abc123 -> preview/__preview__abc123)
        data_path = package_path.replace(".", "/")
        
        for trace in traces:
            try:
                resp = await self._opa.post(
                    f"{self._opa_base}/v1/data/{data_path}/allow",
                    json={"input": trace},
                )
                allowed = resp.json().get("result", False) is True
            except Exception:
                allowed = False  # treat OPA call failure as deny
            results.append(allowed)
        return results

    def _rewrite_package_name(self, rego_body: str, new_package: str) -> str:
        """
        Rewrite the package declaration in a Rego policy to use a unique preview package.
        
        Handles patterns like:
        - package contextiq.example
        - package contextiq.example.subpolicy
        """
        # Match package declaration at the start of the file (possibly after comments)
        pattern = r'^(\s*package\s+)[a-zA-Z_][a-zA-Z0-9_.]*(\s*)$'
        replacement = rf'\1{new_package}\2'
        
        rewritten = re.sub(pattern, replacement, rego_body, count=1, flags=re.MULTILINE)
        
        if rewritten == rego_body:
            # No package declaration found - add one
            logger.warning("No package declaration found in preview Rego body, prepending default")
            rewritten = f"package {new_package}\n\n{rego_body}"
        
        return rewritten
