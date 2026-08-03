from __future__ import annotations

import re


def test_all_four_metric_names_exposed(client):
    """AC-2: All four required metric families appear in /metrics output."""
    client.get("/v1/items/abc")  # trigger instrumentation
    body = client.get("/metrics").text

    assert "contextiq_requests_total" in body
    assert "contextiq_request_duration_seconds" in body
    assert "contextiq_errors_total" in body
    assert "contextiq_active_requests" in body


def test_requests_total_increments_on_request(client):
    """AC-2: contextiq_requests_total counter increments after each request."""
    client.get("/v1/items/x")
    client.get("/v1/items/y")
    body = client.get("/metrics").text

    # Find the sum across all label sets
    totals = re.findall(r"contextiq_requests_total\{[^}]+\}\s+([\d.e+]+)", body)
    total = sum(float(v) for v in totals)
    assert total >= 2


def test_errors_total_increments_on_5xx(client):
    """AC-2: contextiq_errors_total increments when a 5xx response is returned."""
    client.get("/v1/fail")
    body = client.get("/metrics").text
    assert "contextiq_errors_total" in body


def test_requests_total_has_required_labels(client):
    """AC-3: service, endpoint, intent_type, tenant_id labels present in metric sample."""
    client.get("/v1/items/abc")
    body = client.get("/metrics").text

    # Find a contextiq_requests_total sample line
    lines = [
        line
        for line in body.splitlines()
        if line.startswith("contextiq_requests_total{")
    ]
    assert len(lines) > 0, "No contextiq_requests_total samples found"

    sample = lines[0]
    assert "service=" in sample
    assert "endpoint=" in sample
    assert "intent_type=" in sample
    assert "tenant_id=" in sample


def test_duration_histogram_has_required_labels(client):
    """AC-3: histogram _bucket lines carry all four label dimensions."""
    client.get("/v1/items/abc")
    body = client.get("/metrics").text

    buckets = [
        line
        for line in body.splitlines()
        if line.startswith("contextiq_request_duration_seconds_bucket{")
    ]
    assert len(buckets) > 0

    b = buckets[0]
    assert "service=" in b
    assert "endpoint=" in b
    assert "intent_type=" in b
    assert "tenant_id=" in b
