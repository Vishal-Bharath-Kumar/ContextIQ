"""PolicyPreviewService — simulate a draft Rego policy against recent traces.

Implements AC-3: pushes the draft body to OPA under a temporary policy name,
evaluates the last 100 execution traces, then deletes the temporary policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import uuid
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.trace.models import TraceRecord
from src.audit.trace.object_store import TraceObjectStore
from src.audit.trace.schemas import ExecutionTrace, RetrievedChunkSummary
from src.governance.policy.schemas import PolicyPreviewRequest, PolicyPreviewResult

logger = logging.getLogger(__name__)

_PREVIEW_TRACE_LIMIT = 100
_TEMP_POLICY_PREFIX = "__preview__"


@dataclass(frozen=True)
class PreviewTraceInput:
    request_id: str
    inputs: list[dict[str, Any]]


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
        object_store: TraceObjectStore | None = None,
    ) -> None:
        self._session = session
        self._opa = opa_client
        self._opa_base = opa_base.rstrip("/")
        self._object_store = object_store

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
                traces[i].request_id
                for i, r in enumerate(results)
                if not r
            ],
        )

    async def _load_recent_traces(self) -> list[PreviewTraceInput]:
        """Load the last 100 traces and build ChunkAuthzInput-shaped preview payloads."""
        rows = (
            await self._session.execute(
                select(TraceRecord)
                .order_by(desc(TraceRecord.timestamp))
                .limit(_PREVIEW_TRACE_LIMIT)
            )
        ).scalars().all()

        traces: list[PreviewTraceInput] = []
        for row in rows:
            trace = await self._load_full_trace(row)
            if trace is None:
                traces.append(self._build_fallback_trace_input(row))
                continue
            traces.append(self._build_trace_input(trace))
        return traces

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
        traces: list[PreviewTraceInput],
    ) -> list[bool]:
        """Evaluate each trace against the temporary policy; deny if any chunk is denied."""
        results: list[bool] = []
        data_path = package_path.replace(".", "/")

        for trace in traces:
            results.append(await self._evaluate_trace(data_path, trace))
        return results

    async def _load_full_trace(self, row: TraceRecord) -> ExecutionTrace | None:
        if self._object_store is None:
            return None

        try:
            return await self._object_store.read(
                object_key=row.object_key,
                version_id=row.object_version or None,
            )
        except Exception as exc:
            logger.warning(
                "Policy preview fallback: failed to load full trace request_id=%s: %s",
                row.request_id,
                exc,
            )
            return None

    def _build_trace_input(self, trace: ExecutionTrace) -> PreviewTraceInput:
        chunks = (
            trace.retrieved_chunks_pre_compression
            or trace.retrieved_chunks_post_compression
        )
        inputs = [
            self._chunk_input_from_summary(trace, chunk)
            for chunk in chunks
        ]
        if not inputs:
            inputs = [self._synthetic_input(trace.tenant_id, trace.user_roles, trace.request_id)]
        return PreviewTraceInput(request_id=str(trace.request_id), inputs=inputs)

    def _build_fallback_trace_input(self, row: TraceRecord) -> PreviewTraceInput:
        return PreviewTraceInput(
            request_id=str(row.request_id),
            inputs=[self._synthetic_input(row.tenant_id, [], row.request_id)],
        )

    def _chunk_input_from_summary(
        self,
        trace: ExecutionTrace,
        chunk: RetrievedChunkSummary,
    ) -> dict[str, Any]:
        return {
            "user_roles": list(trace.user_roles),
            "tenant_id": trace.tenant_id,
            "source_id": chunk.source_id,
            "chunk_id": chunk.chunk_id,
            "document_id": "",
            "classification_label": chunk.classification_label,
        }

    def _synthetic_input(
        self,
        tenant_id: str,
        user_roles: list[str],
        request_id: uuid.UUID,
    ) -> dict[str, Any]:
        return {
            "user_roles": list(user_roles),
            "tenant_id": tenant_id,
            "source_id": "preview-trace",
            "chunk_id": str(request_id),
            "document_id": "",
            "classification_label": "internal",
        }

    async def _evaluate_trace(
        self,
        data_path: str,
        trace: PreviewTraceInput,
    ) -> bool:
        if not trace.inputs:
            return True

        for item in trace.inputs:
            if not await self._evaluate_input(data_path, item):
                return False
        return True

    async def _evaluate_input(self, data_path: str, item: dict[str, Any]) -> bool:
        try:
            resp = await self._opa.post(
                f"{self._opa_base}/v1/data/{data_path}/allow",
                json={"input": item},
            )
            return resp.json().get("result", False) is True
        except Exception:
            return False

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
