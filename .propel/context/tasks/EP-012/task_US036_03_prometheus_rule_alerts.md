# TASK-US036-03 — `PrometheusRule` Resource (3 Alert Rules)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US036-03 |
| User Story | US-036 |
| Epic | EP-012 — Observability & AI Analytics |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the `PrometheusRule` Kubernetes custom resource containing the three required alert rules (AC-6): `ContextIQHighErrorRate` (error rate > 5%), `ContextIQHighP95Latency` (p95 latency > 3 s), and `ContextIQConnectorFailureRate` (connector failure > 10%). Each rule uses the labelled metrics defined in TASK-US036-01 and includes `for`, `severity`, `runbook_url`, and `summary` annotations following SRE best practice.

## Implementation Details

**Technology:** Kubernetes YAML, Prometheus Operator `PrometheusRule` CRD (`monitoring.coreos.com/v1`), PromQL

**File locations:**
- `k8s/monitoring/alert-rules/contextiq-platform.yaml` — `PrometheusRule` resource

---

### `PrometheusRule` manifest

```yaml
# k8s/monitoring/alert-rules/contextiq-platform.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: contextiq-platform-alerts
  namespace: contextiq
  labels:
    # Must match Prometheus CR's ruleSelector (TASK-US036-02)
    prometheus: contextiq
    role: alert-rules
spec:
  groups:

    # ------------------------------------------------------------------ #
    # Group 1 — Request Error Rate                                        #
    # ------------------------------------------------------------------ #
    - name: contextiq.error_rate
      interval: 30s
      rules:

        # AC-6a: Error rate > 5% over a 5-minute window, per service
        - alert: ContextIQHighErrorRate
          expr: |
            (
              sum by (service, tenant_id) (
                rate(contextiq_errors_total[5m])
              )
              /
              sum by (service, tenant_id) (
                rate(contextiq_requests_total[5m])
              )
            ) > 0.05
          for: 2m
          labels:
            severity: critical
            team: platform-sre
          annotations:
            summary: >-
              High error rate on {{ $labels.service }}
              (tenant {{ $labels.tenant_id }}): {{ $value | humanizePercentage }}
            description: >-
              The 5-minute error rate for service '{{ $labels.service }}'
              has exceeded 5% for the last 2 minutes.
              Current value: {{ $value | humanizePercentage }}.
            runbook_url: https://runbooks.contextiq.internal/alerts/ContextIQHighErrorRate

    # ------------------------------------------------------------------ #
    # Group 2 — Request Latency                                           #
    # ------------------------------------------------------------------ #
    - name: contextiq.latency
      interval: 30s
      rules:

        # AC-6b: p95 request duration > 3 s over a 5-minute window, per service
        - alert: ContextIQHighP95Latency
          expr: |
            histogram_quantile(
              0.95,
              sum by (service, tenant_id, le) (
                rate(contextiq_request_duration_seconds_bucket[5m])
              )
            ) > 3.0
          for: 5m
          labels:
            severity: warning
            team: platform-sre
          annotations:
            summary: >-
              p95 latency on {{ $labels.service }}
              (tenant {{ $labels.tenant_id }}) exceeds 3 s
            description: >-
              The 95th-percentile request duration for service '{{ $labels.service }}'
              has been above 3 s for 5 minutes.
              Current p95: {{ $value | humanizeDuration }}.
            runbook_url: https://runbooks.contextiq.internal/alerts/ContextIQHighP95Latency

        # Supplementary: p99 > 10 s — page-worthy
        - alert: ContextIQCriticalP99Latency
          expr: |
            histogram_quantile(
              0.99,
              sum by (service, tenant_id, le) (
                rate(contextiq_request_duration_seconds_bucket[5m])
              )
            ) > 10.0
          for: 2m
          labels:
            severity: critical
            team: platform-sre
          annotations:
            summary: >-
              p99 latency on {{ $labels.service }}
              (tenant {{ $labels.tenant_id }}) exceeds 10 s
            runbook_url: https://runbooks.contextiq.internal/alerts/ContextIQCriticalP99Latency

    # ------------------------------------------------------------------ #
    # Group 3 — Connector Failure Rate                                    #
    # ------------------------------------------------------------------ #
    - name: contextiq.connectors
      interval: 30s
      rules:

        # AC-6c: Connector failure rate > 10% over a 5-minute window
        # Uses the connector-specific error metric; connector sync jobs
        # expose contextiq_errors_total{endpoint="/v1/knowledge-sources/{id}/sync"}.
        - alert: ContextIQConnectorFailureRate
          expr: |
            (
              sum by (service, tenant_id) (
                rate(contextiq_errors_total{endpoint=~"/v1/knowledge-sources.*"}[5m])
              )
              /
              sum by (service, tenant_id) (
                rate(contextiq_requests_total{endpoint=~"/v1/knowledge-sources.*"}[5m])
              )
            ) > 0.10
          for: 5m
          labels:
            severity: warning
            team: platform-sre
          annotations:
            summary: >-
              Connector failure rate on {{ $labels.service }}
              (tenant {{ $labels.tenant_id }}) exceeds 10%
            description: >-
              More than 10% of knowledge source sync requests are failing.
              Current value: {{ $value | humanizePercentage }}.
              Check connector credentials, Vault availability, and source reachability.
            runbook_url: https://runbooks.contextiq.internal/alerts/ContextIQConnectorFailureRate

        # Supplementary: Dead-letter queue depth for entity extraction
        # (uses governance_policy_denials_total as a proxy indicator — replace
        # with a dedicated DLQ depth metric when Kafka consumer lag is exposed)
        - alert: ContextIQEntityExtractionDLQNonEmpty
          expr: |
            sum by (tenant_id) (
              increase(contextiq_errors_total{
                endpoint=~".*entity.*|.*chunk.*"
              }[15m])
            ) > 50
          for: 10m
          labels:
            severity: warning
            team: knowledge-platform
          annotations:
            summary: >-
              High entity extraction error volume for tenant {{ $labels.tenant_id }}
            runbook_url: https://runbooks.contextiq.internal/alerts/ContextIQEntityExtractionDLQ
```

---

### Runbook stubs

Create placeholder runbook documents at the paths referenced in `runbook_url` annotations. These are stub files — engineering fills in remediation steps:

```
docs/runbooks/ContextIQHighErrorRate.md
docs/runbooks/ContextIQHighP95Latency.md
docs/runbooks/ContextIQCriticalP99Latency.md
docs/runbooks/ContextIQConnectorFailureRate.md
docs/runbooks/ContextIQEntityExtractionDLQ.md
```

Each stub follows the structure: **Impact → Diagnosis steps → Remediation → Escalation**.

## Acceptance Criteria

- [ ] `kubectl apply --dry-run=client -f k8s/monitoring/alert-rules/contextiq-platform.yaml` succeeds without errors
- [ ] `PrometheusRule` carries `labels.prometheus: contextiq` matching the `Prometheus` CR `ruleSelector` (TASK-US036-02)
- [ ] `ContextIQHighErrorRate` fires when simulated error rate exceeds 0.05 (AC-6)
- [ ] `ContextIQHighP95Latency` uses `histogram_quantile(0.95, ...)` over `contextiq_request_duration_seconds_bucket` (AC-6)
- [ ] `ContextIQConnectorFailureRate` targets `endpoint=~"/v1/knowledge-sources.*"` (AC-6)
- [ ] All three AC-6 alert rules include `for`, `severity`, `summary`, `description`, and `runbook_url`

## Dependencies

- TASK-US036-01 — metrics must be registered for PromQL expressions to resolve
- TASK-US036-02 — `Prometheus` CR must have `ruleSelector: matchLabels: prometheus: contextiq`

## Definition of Done

- [ ] YAML lints with `kubectl apply --dry-run=client`
- [ ] PromQL expressions validated with `promtool check rules k8s/monitoring/alert-rules/contextiq-platform.yaml`
- [ ] Reviewed and merged to `main`
