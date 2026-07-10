# TASK-US037-02 — Compression Savings Instrumentation and Prometheus Metrics

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US037-02 |
| User Story | US-037 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Extend the compression node to record `tokens_before_compression` and `tokens_after_compression` per request via `LLMCostRecorder` (AC-2), and expose three Prometheus metrics — `contextiq_compression_tokens_total`, `contextiq_compression_savings_tokens_total`, and `contextiq_compression_savings_ratio` — that feed the Grafana "compression savings %" panel (AC-3). These metrics carry `team_id`, `tenant_id`, and `intent_type` labels so the Grafana dashboard's team/intent filters (AC-6) work correctly.

## Implementation Details

**Technology:** Python 3.11+, `prometheus-client>=0.20`, LangGraph `>=0.2.0`

**File locations:**
- `src/observability/cost/compression_metrics.py` — `CompressionMetricsRecorder` + Prometheus metrics
- `src/agents/nodes/compression_node.py` — extend to call `CompressionMetricsRecorder` (do NOT rewrite)
- `tests/observability/test_compression_metrics.py`

---

### Prometheus metrics for compression

```python
# src/observability/cost/compression_metrics.py
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from prometheus_client import Counter, Histogram

from src.observability.cost.schemas  import CompressionRecord
from src.observability.cost.recorder import LLMCostRecorder

logger = logging.getLogger(__name__)

_LABEL_NAMES = ["service", "team_id", "tenant_id", "intent_type"]

# AC-2 / AC-3: token counts
contextiq_compression_tokens_total = Counter(
    "contextiq_compression_tokens_total",
    "Cumulative token count entering and leaving the compression node.",
    _LABEL_NAMES + ["stage"],   # stage: "before" | "after"
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
```

---

### `CompressionMetricsRecorder`

```python
class CompressionMetricsRecorder:
    """
    Records compression savings to both Prometheus (for Grafana, AC-3) and
    Langfuse (for API export / BI tools, AC-2, AC-4).

    Called from the compression node after tokens_before and tokens_after
    are known. All calls are synchronous (Prometheus) + fire-and-forget
    (Langfuse via LLMCostRecorder).
    """

    _SERVICE = "contextiq-api"

    def __init__(self, cost_recorder: LLMCostRecorder) -> None:
        self._recorder = cost_recorder

    def record(self, rec: CompressionRecord) -> None:
        """
        Write Prometheus metrics and enqueue Langfuse event for one request.
        Called synchronously from the compression node — no await required.
        """
        labels = {
            "service":     self._SERVICE,
            "team_id":     rec.team_id,
            "tenant_id":   rec.tenant_id,
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

        # Ratio histogram — guards against zero-before (no content to compress)
        if rec.tokens_before_compression > 0:
            ratio = rec.savings_tokens / rec.tokens_before_compression
            contextiq_compression_savings_ratio.labels(**labels).observe(ratio)

        # Langfuse event (AC-2, AC-4) — fire-and-forget via existing recorder
        self._recorder.record_compression(rec)
        logger.debug(
            "compression.recorded request_id=%s before=%d after=%d savings_pct=%.1f%%",
            rec.request_id, rec.tokens_before_compression,
            rec.tokens_after_compression, rec.savings_pct,
        )
```

---

### Compression node extension

The existing compression node (from US-017) must be extended to call `CompressionMetricsRecorder.record()` after completing compression. Add only the instrumentation lines — do NOT alter existing compression logic:

```python
# src/agents/nodes/compression_node.py  (extend — do NOT rewrite)
# At the END of the existing async def compression_node(state: AgentState) function,
# before returning the updated state:

    # --- NEW instrumentation block (US-037 AC-2) ---
    from datetime import datetime, timezone
    from src.observability.cost.schemas            import CompressionRecord
    from src.observability.cost.compression_metrics import CompressionMetricsRecorder
    from src.observability.cost.recorder            import LLMCostRecorder

    jwt_claims: dict = state.get("jwt_claims") or {}
    comp_rec = CompressionRecord(
        request_id                = _get_request_id(state),
        tenant_id                 = state.get("tenant_id") or "default",
        user_id                   = jwt_claims.get("sub") or "anonymous",
        team_id                   = jwt_claims.get("team_id") or jwt_claims.get("groups", ["default"])[0],
        intent_type               = state.get("intent") or "unknown",
        timestamp                 = datetime.now(tz=timezone.utc),
        tokens_before_compression = tokens_before,   # existing local variable
        tokens_after_compression  = tokens_after,    # existing local variable
    )
    _get_compression_recorder(state).record(comp_rec)
    # --- END instrumentation block ---
```

`_get_compression_recorder(state)` follows the module-level singleton pattern established in TASK-US034-04 and TASK-US032-04:

```python
_DEFAULT_COMPRESSION_RECORDER: CompressionMetricsRecorder | None = None

def set_compression_recorder(recorder: CompressionMetricsRecorder) -> None:
    global _DEFAULT_COMPRESSION_RECORDER
    _DEFAULT_COMPRESSION_RECORDER = recorder

def _get_compression_recorder(state) -> CompressionMetricsRecorder:
    config = state.get("_config") or {}
    return config.get("compression_recorder") or _DEFAULT_COMPRESSION_RECORDER
```

---

### `AgentState` extensions

```python
# src/agents/state.py  (extend existing TypedDict)
    team_id: str | None    # populated from JWT claims by gateway middleware
```

## Acceptance Criteria

- [ ] After a compression node execution, `contextiq_compression_tokens_total{stage="before"}` has increased by `tokens_before_compression` (AC-2)
- [ ] After a compression node execution, `contextiq_compression_tokens_total{stage="after"}` has increased by `tokens_after_compression` (AC-2)
- [ ] `contextiq_compression_savings_ratio` histogram observes a value in `[0, 1]` for every request with `tokens_before > 0` (AC-3)
- [ ] When `tokens_before_compression == 0`, no ratio observation is recorded (no `NaN` or `Inf` in metrics)
- [ ] `LLMCostRecorder.record_compression()` is called once per compression node execution (AC-2)
- [ ] All four Prometheus label dimensions (`service`, `team_id`, `tenant_id`, `intent_type`) are present in each metric sample (AC-6 filter support)

## Dependencies

- TASK-US037-01 (`LLMCallRecord`, `CompressionRecord`, `LLMCostRecorder`)
- US-017 compression node (existing `compression_node.py` — location to extend)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
