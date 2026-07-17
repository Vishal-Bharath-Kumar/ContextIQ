from __future__ import annotations

import pathlib
import subprocess

import yaml

RULES_PATH = pathlib.Path("k8s/monitoring/alert-rules/contextiq-platform.yaml")


def test_promtool_check_rules():
    """
    AC-6: promtool validates that all PromQL expressions in the PrometheusRule
    are syntactically correct and all required fields (for, severity) are present.
    Skips gracefully when promtool is not installed in the local environment.
    """
    result = subprocess.run(
        ["which", "promtool"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        import pytest

        pytest.skip("promtool not available in this environment (required in CI)")

    result = subprocess.run(
        ["promtool", "check", "rules", str(RULES_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"promtool check rules failed:\n{result.stdout}\n{result.stderr}"
    )


def test_alert_rules_cover_all_three_ac6_conditions():
    """AC-6: The PrometheusRule defines alerts for all three required conditions."""
    rules_yaml = yaml.safe_load(RULES_PATH.read_text())
    all_alerts = [
        rule["alert"]
        for group in rules_yaml["spec"]["groups"]
        for rule in group["rules"]
        if "alert" in rule
    ]
    # AC-6a: error rate > 5%
    assert any("ErrorRate" in a for a in all_alerts), "Missing error rate alert rule"
    # AC-6b: p95 latency > 3 s
    assert any(
        "Latency" in a or "P95" in a for a in all_alerts
    ), "Missing p95 latency alert rule"
    # AC-6c: connector failure > 10%
    assert any("Connector" in a for a in all_alerts), "Missing connector failure alert rule"


def test_alert_rules_have_severity_labels():
    """AC-6: All alert rules carry a severity label (critical or warning)."""
    rules_yaml = yaml.safe_load(RULES_PATH.read_text())
    for group in rules_yaml["spec"]["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                assert "severity" in rule.get("labels", {}), (
                    f"Alert '{rule['alert']}' is missing a severity label"
                )


def test_alert_rules_have_runbook_urls():
    """AC-6: All alert rules reference a runbook_url annotation."""
    rules_yaml = yaml.safe_load(RULES_PATH.read_text())
    for group in rules_yaml["spec"]["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                assert "runbook_url" in rule.get("annotations", {}), (
                    f"Alert '{rule['alert']}' is missing runbook_url annotation"
                )
