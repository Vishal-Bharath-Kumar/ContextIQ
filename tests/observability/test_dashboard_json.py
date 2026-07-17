from __future__ import annotations

import json
import pathlib

import yaml

DASHBOARD_PATH = pathlib.Path(
    "k8s/monitoring/grafana/dashboard-contextiq-overview.yaml"
)
PROMETHEUS_CR_PATH = pathlib.Path("k8s/monitoring/prometheus.yaml")


def _load_dashboard_json() -> dict:
    """Extract the JSON from the YAML ConfigMap data value."""
    cm = yaml.safe_load(DASHBOARD_PATH.read_text())
    raw = cm["data"]["contextiq-platform-overview.json"]
    return json.loads(raw)


def test_dashboard_title():
    """AC-4: Dashboard is titled 'ContextIQ Platform Overview'."""
    d = _load_dashboard_json()
    assert d["title"] == "ContextIQ Platform Overview"


def test_dashboard_has_six_panels():
    """AC-4: Exactly 6 panels are provisioned."""
    d = _load_dashboard_json()
    panels = d.get("panels", [])
    assert len(panels) == 6, f"Expected 6 panels, got {len(panels)}"


def test_dashboard_panel_ids_unique():
    """AC-4: All panel IDs are unique."""
    d = _load_dashboard_json()
    ids = [p["id"] for p in d["panels"]]
    assert len(ids) == len(set(ids))


def test_dashboard_has_template_variables():
    """AC-4: Dashboard has $service and $tenant_id template variables."""
    d = _load_dashboard_json()
    names = [t["name"] for t in d.get("templating", {}).get("list", [])]
    assert "service" in names
    assert "tenant_id" in names


def test_dashboard_panels_have_prometheus_targets():
    """AC-4: Every panel has at least one Prometheus target with a non-empty expr."""
    d = _load_dashboard_json()
    for panel in d["panels"]:
        targets = panel.get("targets", [])
        assert len(targets) > 0, f"Panel '{panel.get('title')}' has no targets"
        for t in targets:
            assert t.get("expr"), f"Panel '{panel.get('title')}' has empty expr"


def test_prometheus_cr_has_15d_retention():
    """AC-5: Prometheus CR spec has retention: 15d."""
    cr = yaml.safe_load(PROMETHEUS_CR_PATH.read_text())
    assert cr["spec"]["retention"] == "15d"
