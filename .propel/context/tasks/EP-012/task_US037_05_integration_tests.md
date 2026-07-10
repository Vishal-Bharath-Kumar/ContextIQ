# TASK-US037-05 — Integration Tests Covering All 6 Acceptance Criteria

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US037-05 |
| User Story | US-037 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Write the test suite covering all 6 US-037 acceptance criteria: Langfuse records all six required LLM call fields (AC-1), compression node records both token counts (AC-2), Grafana dashboard has all four required chart types with correct metric expressions (AC-3), Langfuse metadata structure supports API export queries (AC-4), retention configuration documented and startup-validated (AC-5), and dashboard template variables match the four AC-6 filter dimensions.

## Implementation Details

**Technology:** Python 3.11+, pytest, pytest-asyncio, `AsyncMock`, `unittest.mock`, Python `json` + `yaml` for dashboard/retention tests

**File locations:**
- `tests/observability/test_llm_cost_recorder.py` — AC-1, AC-4
- `tests/observability/test_compression_metrics.py` — AC-2
- `tests/observability/test_llm_metrics_node.py` — AC-1, AC-3 (Prometheus counter assertions)
- `tests/observability/test_ai_cost_dashboard.py` — AC-3, AC-5, AC-6

---

### Shared fixtures

```python
# tests/observability/conftest.py  (extend existing file)
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.observability.cost.schemas import LLMCallRecord, CompressionRecord

REQUEST_ID = uuid.uuid4()
TENANT_ID  = "acme"
USER_ID    = "user-abc123"
TEAM_ID    = "platform-eng"

SAMPLE_LLM_RECORD = LLMCallRecord(
    request_id        = REQUEST_ID,
    tenant_id         = TENANT_ID,
    model_id          = "gpt-4o",
    prompt_tokens     = 512,
    completion_tokens = 128,
    cost_usd          = 0.00480,
    user_id           = USER_ID,
    team_id           = TEAM_ID,
    intent_type       = "technical_support",
    timestamp         = datetime.now(tz=timezone.utc),
)

SAMPLE_COMPRESSION_RECORD = CompressionRecord(
    request_id                = REQUEST_ID,
    tenant_id                 = TENANT_ID,
    user_id                   = USER_ID,
    team_id                   = TEAM_ID,
    intent_type               = "technical_support",
    timestamp                 = datetime.now(tz=timezone.utc),
    tokens_before_compression = 800,
    tokens_after_compression  = 400,
)


@pytest.fixture
def mock_langfuse():
    """Patch Langfuse SDK so no real HTTP calls are made."""
    with patch("src.observability.cost.recorder.Langfuse") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance
```

---

### AC-1 — Langfuse records all six required LLM call fields

```python
# tests/observability/test_llm_cost_recorder.py
def test_record_llm_call_sends_all_six_ac1_fields(mock_langfuse):
    """AC-1: all six required metadata fields present in langfuse.generation() call."""
    from src.observability.cost.recorder import LLMCostRecorder

    recorder = LLMCostRecorder()
    recorder.record_llm_call(SAMPLE_LLM_RECORD)

    mock_langfuse.generation.assert_called_once()
    call_kwargs = mock_langfuse.generation.call_args.kwargs
    metadata    = call_kwargs.get("metadata", {})

    # AC-1: all six fields
    assert metadata["model_id"]          == "gpt-4o"
    assert metadata["prompt_tokens"]     == 512
    assert metadata["completion_tokens"] == 128
    assert metadata["cost_usd"]          == 0.00480
    assert metadata["user_id"]           == USER_ID
    assert metadata["team_id"]           == TEAM_ID


def test_record_llm_call_does_not_raise_on_langfuse_error(mock_langfuse):
    """AC-1: recorder silently handles Langfuse SDK exceptions."""
    from src.observability.cost.recorder import LLMCostRecorder

    mock_langfuse.generation.side_effect = RuntimeError("Langfuse down")
    recorder = LLMCostRecorder()
    # Should not raise
    recorder.record_llm_call(SAMPLE_LLM_RECORD)
```

---

### AC-2 — Compression records both required token fields

```python
# tests/observability/test_compression_metrics.py
def test_compression_langfuse_event_contains_both_token_fields(mock_langfuse):
    """AC-2: langfuse.event() metadata includes tokens_before and tokens_after."""
    from src.observability.cost.recorder import LLMCostRecorder

    recorder = LLMCostRecorder()
    recorder.record_compression(SAMPLE_COMPRESSION_RECORD)

    mock_langfuse.event.assert_called_once()
    metadata = mock_langfuse.event.call_args.kwargs.get("metadata", {})
    assert metadata["tokens_before_compression"] == 800
    assert metadata["tokens_after_compression"]  == 400
    assert metadata["savings_pct"]               == 50.0


def test_compression_prometheus_counters_incremented():
    """AC-2: Prometheus compression counters increase by the correct token counts."""
    from unittest.mock import MagicMock
    from src.observability.cost.recorder           import LLMCostRecorder
    from src.observability.cost.compression_metrics import (
        CompressionMetricsRecorder,
        contextiq_compression_tokens_total,
        contextiq_compression_savings_tokens_total,
    )

    mock_recorder = MagicMock(spec=LLMCostRecorder)
    recorder      = CompressionMetricsRecorder(mock_recorder)

    labels_before = {"service": "contextiq-api", "team_id": TEAM_ID,
                     "tenant_id": TENANT_ID, "intent_type": "technical_support",
                     "stage": "before"}
    labels_after  = {**labels_before, "stage": "after"}
    labels_savings= {k: v for k, v in labels_before.items() if k != "stage"}

    before_val = contextiq_compression_tokens_total.labels(**labels_before)._value.get()
    after_val  = contextiq_compression_tokens_total.labels(**labels_after)._value.get()
    savings_val = contextiq_compression_savings_tokens_total.labels(**labels_savings)._value.get()

    recorder.record(SAMPLE_COMPRESSION_RECORD)

    assert contextiq_compression_tokens_total.labels(**labels_before)._value.get() - before_val == 800
    assert contextiq_compression_tokens_total.labels(**labels_after)._value.get()  - after_val  == 400
    assert contextiq_compression_savings_tokens_total.labels(**labels_savings)._value.get() - savings_val == 400


def test_compression_no_ratio_observation_when_before_is_zero():
    """AC-2: ratio histogram is not observed when tokens_before == 0 (no division by zero)."""
    from unittest.mock import MagicMock, patch
    from src.observability.cost.recorder           import LLMCostRecorder
    from src.observability.cost.compression_metrics import (
        CompressionMetricsRecorder, contextiq_compression_savings_ratio,
    )
    from src.observability.cost.schemas import CompressionRecord
    from datetime import datetime, timezone

    zero_rec = CompressionRecord(
        request_id=REQUEST_ID, tenant_id=TENANT_ID, user_id=USER_ID,
        team_id=TEAM_ID, intent_type="test",
        timestamp=datetime.now(tz=timezone.utc),
        tokens_before_compression=0,
        tokens_after_compression=0,
    )
    mock_recorder = MagicMock(spec=LLMCostRecorder)
    cr = CompressionMetricsRecorder(mock_recorder)

    with patch.object(contextiq_compression_savings_ratio, "labels") as mock_labels:
        cr.record(zero_rec)
        mock_labels.assert_not_called()
```

---

### AC-3 — Prometheus cost counters incremented by `llm_metrics_node`

```python
# tests/observability/test_llm_metrics_node.py
async def test_llm_metrics_node_increments_cost_counter():
    """AC-3: contextiq_llm_cost_usd_total increments after llm_metrics_node runs."""
    from unittest.mock import MagicMock, patch
    from src.observability.cost.llm_metrics  import (
        llm_metrics_node, set_llm_cost_recorder,
        contextiq_llm_cost_usd_total,
    )
    from src.observability.cost.recorder import LLMCostRecorder

    mock_rec = MagicMock(spec=LLMCostRecorder)
    set_llm_cost_recorder(mock_rec)

    labels = {
        "service": "contextiq-api", "model_id": "gpt-4o",
        "team_id": TEAM_ID, "tenant_id": TENANT_ID, "intent_type": "technical_support",
    }
    before = contextiq_llm_cost_usd_total.labels(**labels)._value.get()

    state = {
        "request_id":       str(REQUEST_ID),
        "tenant_id":        TENANT_ID,
        "team_id":          TEAM_ID,
        "jwt_claims":       {"sub": USER_ID},
        "intent":           "technical_support",
        "model_selected":   "gpt-4o",
        "prompt_tokens":    512,
        "completion_tokens": 128,
    }
    with patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.00480):
        await llm_metrics_node(state)

    after = contextiq_llm_cost_usd_total.labels(**labels)._value.get()
    assert abs((after - before) - 0.00480) < 1e-6


async def test_llm_metrics_node_exposes_llm_cost_usd_in_state():
    """AC-3: llm_cost_usd added to returned AgentState."""
    from unittest.mock import MagicMock, patch
    from src.observability.cost.llm_metrics  import llm_metrics_node, set_llm_cost_recorder
    from src.observability.cost.recorder     import LLMCostRecorder

    set_llm_cost_recorder(MagicMock(spec=LLMCostRecorder))
    state = {
        "request_id": str(REQUEST_ID), "tenant_id": TENANT_ID,
        "model_selected": "gpt-4o", "prompt_tokens": 100, "completion_tokens": 50,
    }
    with patch("src.observability.cost.llm_metrics._compute_cost", return_value=0.001):
        result = await llm_metrics_node(state)

    assert "llm_cost_usd" in result
    assert abs(result["llm_cost_usd"] - 0.001) < 1e-9
```

---

### AC-4 — Langfuse metadata queryable (field structure)

```python
def test_langfuse_generation_metadata_is_queryable_by_all_six_fields(mock_langfuse):
    """
    AC-4: The metadata dict passed to langfuse.generation() contains each of the
    six AC-1 fields as top-level keys — enabling Langfuse API filtering by any of them.
    """
    from src.observability.cost.recorder import LLMCostRecorder
    recorder = LLMCostRecorder()
    recorder.record_llm_call(SAMPLE_LLM_RECORD)

    metadata = mock_langfuse.generation.call_args.kwargs["metadata"]
    required_keys = {"model_id", "prompt_tokens", "completion_tokens",
                     "cost_usd", "user_id", "team_id"}
    assert required_keys.issubset(set(metadata.keys()))
```

---

### AC-5 — Retention configuration present and >= 12 months

```python
# tests/observability/test_ai_cost_dashboard.py
def test_langfuse_settings_required_retention_is_12_months():
    """AC-5: required_retention_months default is 12."""
    from src.observability.cost.settings import LangfuseProjectSettings
    settings = LangfuseProjectSettings()
    assert settings.required_retention_months >= 12
```

---

### AC-3 + AC-6 — Dashboard JSON: four AC-3 charts + four AC-6 filter variables

```python
# tests/observability/test_ai_cost_dashboard.py (continued)
import json, pathlib, yaml

DASHBOARD_PATH = pathlib.Path(
    "k8s/monitoring/grafana/dashboard-ai-cost-efficiency.yaml"
)


def _load_dashboard() -> dict:
    cm  = yaml.safe_load(DASHBOARD_PATH.read_text())
    raw = cm["data"]["ai-cost-efficiency.json"]
    return json.loads(raw)


def test_dashboard_title():
    assert _load_dashboard()["title"] == "AI Cost & Efficiency"


def test_dashboard_has_four_required_chart_types():
    """AC-3: daily cost by model, cost per team, compression savings %, token budget."""
    d      = _load_dashboard()
    titles = [p["title"] for p in d["panels"]]
    # Verify the four AC-3 required charts are present (partial title match)
    assert any("Daily" in t and "Cost" in t and "Model" in t for t in titles), \
        "Missing 'daily cost by model' panel"
    assert any("Cost" in t and ("Team" in t or "User" in t) for t in titles), \
        "Missing 'cost per user/team' panel"
    assert any("Compression" in t and "Saving" in t for t in titles), \
        "Missing 'compression savings' panel"
    assert any("Token" in t and ("Budget" in t or "Utilis" in t or "Utiliz" in t) for t in titles), \
        "Missing 'token budget utilisation' panel"


def test_dashboard_template_variables_cover_ac6_filters():
    """AC-6: $team, $model, $intent_type present as template variables."""
    d     = _load_dashboard()
    names = [t["name"] for t in d.get("templating", {}).get("list", [])]
    assert "team"        in names, "Missing $team variable"
    assert "model"       in names, "Missing $model variable"
    assert "intent_type" in names, "Missing $intent_type variable"
    # $date_range is the native Grafana time picker — not a templating variable


def test_daily_cost_panel_uses_correct_metric():
    """AC-3: Daily cost panel queries contextiq_llm_cost_usd_total."""
    d          = _load_dashboard()
    cost_panel = next(p for p in d["panels"] if "Daily" in p.get("title", ""))
    exprs      = [t["expr"] for t in cost_panel.get("targets", [])]
    assert any("contextiq_llm_cost_usd_total" in e for e in exprs)


def test_compression_panel_uses_savings_ratio_metric():
    """AC-3: Compression savings panel queries contextiq_compression_savings_ratio_bucket."""
    d     = _load_dashboard()
    panel = next(p for p in d["panels"] if "Compression" in p.get("title", "") and "Saving" in p.get("title", ""))
    exprs = [t["expr"] for t in panel.get("targets", [])]
    assert any("contextiq_compression_savings_ratio" in e for e in exprs)
```

## Acceptance Criteria

- [ ] AC-1: `test_record_llm_call_sends_all_six_ac1_fields` passes; all six fields verified in Langfuse call
- [ ] AC-2: `test_compression_prometheus_counters_incremented` passes; before/after token counters increment correctly
- [ ] AC-2: `test_compression_no_ratio_observation_when_before_is_zero` passes; no histogram observation on zero-token requests
- [ ] AC-3: Prometheus counter assertion in `test_llm_metrics_node_increments_cost_counter` passes
- [ ] AC-4: `test_langfuse_generation_metadata_is_queryable_by_all_six_fields` confirms all six keys at top level
- [ ] AC-5: `test_langfuse_settings_required_retention_is_12_months` confirms default is ≥ 12
- [ ] AC-3 + AC-6: dashboard structure tests confirm four chart types and three template variable names

## Dependencies

- TASK-US037-01 (`LLMCallRecord`, `CompressionRecord`, `LLMCostRecorder`)
- TASK-US037-02 (`CompressionMetricsRecorder`, compression Prometheus metrics)
- TASK-US037-03 (`llm_metrics_node`, cost Prometheus metrics)
- TASK-US037-04 (`dashboard-ai-cost-efficiency.yaml`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] All tests pass with `AsyncMock` / `MagicMock` — no live Langfuse or Prometheus in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
