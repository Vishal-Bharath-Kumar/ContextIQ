# Runbook: ContextIQHighErrorRate

**Alert:** `ContextIQHighErrorRate`
**Severity:** critical
**Team:** platform-sre

---

## Impact

The 5-minute error rate for a service has exceeded **5%** for at least 2 minutes. Requests are failing for the affected tenant, which may result in degraded API responses or data pipeline interruptions.

---

## Diagnosis Steps

1. Identify the affected service and tenant:
   ```promql
   sum by (service, tenant_id) (rate(contextiq_errors_total[5m]))
   / sum by (service, tenant_id) (rate(contextiq_requests_total[5m]))
   ```
2. Check recent application logs for stack traces:
   ```bash
   kubectl logs -n contextiq -l app=<service> --since=10m | grep -i error
   ```
3. Review recent deployments that may have introduced a regression:
   ```bash
   kubectl rollout history deployment/<service> -n contextiq
   ```
4. Inspect dependent services (database, Kafka, Vault) for health issues.
5. Check the Grafana dashboard **ContextIQ — Request Metrics** for correlated spikes.

---

## Remediation

- If caused by a bad deployment, roll back:
  ```bash
  kubectl rollout undo deployment/<service> -n contextiq
  ```
- If caused by a downstream dependency outage, follow the runbook for that service.
- Increase replicas if load-related:
  ```bash
  kubectl scale deployment/<service> -n contextiq --replicas=<n>
  ```

---

## Escalation

If not resolved within 15 minutes, page the **Platform SRE on-call** via PagerDuty and open a P1 incident in the incident tracker.
