"""Prometheus metrics and recorder for compression savings (TASK-US037-02).

Exposes three metric families consumed by the Grafana "compression savings %" panel (AC-3):
  - contextiq_compression_tokens_total          (Counter, stage label: before|after)
  - contextiq_compression_savings_tokens_total  (Counter)
  - contextiq_compression_savings_ratio         (Histogram)

All metrics carry service, team_id, tenant_id, and intent_type labels so the
Grafana dashboard team/intent filters work correctly (AC-6).
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Histogram

from src.observability.cost.recorder import LLMCostRecorder
from src.observability.cost.schemas import CompressionRecord

logger = logging.getLogger(__name__)

_LABEL_NAMES = ["service", "team_id", "tenant_id", "intent_type"]

# AC-2 / AC-3: cumulative token counts entering and leaving the compression node
contextiq_compression_tokens_total = Counter(
    "contextiq_compression_tokens_total",
    "Cumulative token count entering and leaving the compression node.",
    _LABEL_NAMES + ["stage"],  # stage: "before" | "after"
)

contextiq_compression_savings_tokens_total = Counter(
    "contextiq_compression_savings_tokens_total",
    "Cumulative tokens saved by the compression node.",
    _LABEL_NAMES,
)

# Histogram: distribution of per-request compression ratios (0.0–1.0)
# Used for the Grafana "compression savings %" panel (AC-3)
contextiq_compression_savings_ratio = Histogram(
    "contextiq_compression_savings_ratio",
    "Per-request token compression savings ratio (1 - tokens_after / tokens_before).",
    _LABEL_NAMES,
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)


class CompressionMetricsRecorder:
    """Records compression savings to both Prometheus (AC-3) and Langfuse (AC-2, AC-4).

    Called from the compression node after tokens_before and tokens_after are known.
    Prometheus writes are synchronous; Langfuse is fire-and-forget via LLMCostRecorder.
    """

    _SERVICE = "contextiq-api"

    def __init__(self, cost_recorder: LLMCostRecorder) -> None:
        self._recorder = cost_recorder

    def record(self, rec: CompressionRecord) -> None:
        """Write Prometheus metrics and enqueue a Langfuse event for one request.

        Called synchronously from the compression node — no await required.
        """
        labels = {
            "service": self._SERVICE,
            "team_id": rec.team_id,
            "tenant_id": rec.tenant_id,
            "intent_type": rec.intent_type,
        }

        # Prometheus counters (AC-2, AC-3)
        contextiq_compression_tokens_total.labels(**labels, stage="before").inc(
            rec.tokens_before_compression
        )
        contextiq_compression_tokens_total.labels(**labels, stage="after").inc(
            rec.tokens_after_compression
        )
        contextiq_compression_savings_tokens_total.labels(**labels).inc(
            rec.savings_tokens
        )

        # Ratio histogram — guard against zero-before (no content to compress)
        if rec.tokens_before_compression > 0:
            ratio = rec.savings_tokens / rec.tokens_before_compression
            contextiq_compression_savings_ratio.labels(**labels).observe(ratio)

        # Langfuse event (AC-2, AC-4) — fire-and-forget via existing recorder
        self._recorder.record_compression(rec)

        logger.debug(
            "compression.recorded request_id=%s before=%d after=%d savings_pct=%.1f%%",
            rec.request_id,
            rec.tokens_before_compression,
            rec.tokens_after_compression,
            rec.savings_pct,
        )
