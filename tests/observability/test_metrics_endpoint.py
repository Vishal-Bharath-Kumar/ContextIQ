from __future__ import annotations


def test_metrics_endpoint_returns_200(client):
    """AC-1: /metrics returns HTTP 200."""
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_metrics_content_type_is_prometheus_text(client):
    """AC-1: Content-Type header matches Prometheus text exposition format."""
    resp = client.get("/metrics")
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_body_is_valid_prometheus_text(client):
    """AC-1: Body contains # HELP and # TYPE lines — valid Prometheus format."""
    # Trigger a request to create label combinations
    client.get("/v1/items/abc")
    resp = client.get("/metrics")
    body = resp.text
    assert "# HELP" in body
    assert "# TYPE" in body
