"""Integration tests for the AI Cost & Efficiency Grafana dashboard — AC-3, AC-5, AC-6.

Coverage (TASK-US037-05):
  - AC-3: dashboard has four required chart types with correct metric expressions
  - AC-5: LangfuseProjectSettings.required_retention_months default >= 12
  - AC-6: dashboard template variables include $team, $model, $intent_type
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from src.observability.cost.settings import LangfuseProjectSettings

DASHBOARD_PATH = pathlib.Path(
    "k8s/monitoring/grafana/dashboard-ai-cost-efficiency.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_dashboard() -> dict:
    cm = yaml.safe_load(DASHBOARD_PATH.read_text())
    raw = cm["data"]["ai-cost-efficiency.json"]
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_dashboard_title():
    """Dashboard is titled 'AI Cost & Efficiency'."""
    assert _load_dashboard()["title"] == "AI Cost & Efficiency"


# ---------------------------------------------------------------------------
# AC-3: four required chart types present with correct metric expressions
# ---------------------------------------------------------------------------


def test_dashboard_has_four_required_chart_types():
    """AC-3: daily cost by model, cost per team, compression savings %, token budget."""
    d = _load_dashboard()
    titles = [p["title"] for p in d["panels"]]

    assert any("Daily" in t and "Cost" in t and "Model" in t for t in titles), \
        "Missing 'daily cost by model' panel"
    assert any("Cost" in t and ("Team" in t or "User" in t) for t in titles), \
        "Missing 'cost per user/team' panel"
    assert any("Compression" in t and "Saving" in t for t in titles), \
        "Missing 'compression savings' panel"
    assert any(
        "Token" in t and ("Budget" in t or "Utilis" in t or "Utiliz" in t)
        for t in titles
    ), "Missing 'token budget utilisation' panel"


def test_daily_cost_panel_uses_correct_metric():
    """AC-3: Daily cost panel queries contextiq_llm_cost_usd_total."""
    d = _load_dashboard()
    cost_panel = next(p for p in d["panels"] if "Daily" in p.get("title", ""))
    exprs = [t["expr"] for t in cost_panel.get("targets", [])]
    assert any("contextiq_llm_cost_usd_total" in e for e in exprs)


def test_compression_panel_uses_savings_ratio_metric():
    """AC-3: Compression savings panel queries contextiq_compression_savings_ratio."""
    d = _load_dashboard()
    panel = next(
        p
        for p in d["panels"]
        if "Compression" in p.get("title", "") and "Saving" in p.get("title", "")
    )
    exprs = [t["expr"] for t in panel.get("targets", [])]
    assert any("contextiq_compression_savings_ratio" in e for e in exprs)


# ---------------------------------------------------------------------------
# AC-5: retention configuration >= 12 months
# ---------------------------------------------------------------------------


def test_langfuse_settings_required_retention_is_12_months():
    """AC-5: LangfuseProjectSettings.required_retention_months default is >= 12."""
    settings = LangfuseProjectSettings()
    assert settings.required_retention_months >= 12


# ---------------------------------------------------------------------------
# AC-6: dashboard template variables cover filter dimensions
# ---------------------------------------------------------------------------


def test_dashboard_template_variables_cover_ac6_filters():
    """AC-6: $team, $model, $intent_type present as template variables."""
    d = _load_dashboard()
    names = [t["name"] for t in d.get("templating", {}).get("list", [])]
    assert "team" in names, "Missing $team variable"
    assert "model" in names, "Missing $model variable"
    assert "intent_type" in names, "Missing $intent_type variable"
    # $date_range is the native Grafana time picker — not a templating variable
