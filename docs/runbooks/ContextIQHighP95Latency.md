# Runbook: ContextIQHighP95Latency

**Alert:** `ContextIQHighP95Latency`
**Severity:** warning
**Team:** platform-sre

---

## Impact

The 95th-percentile request duration for a service has exceeded **3 seconds** for at least 5 minutes. The tail of user-facing requests is experiencing significant latency degradation.

---

## Diagnosis Steps

1. Identify the affected service and tenant:
   ```promql
   histogram_quantile(0.95, sum by (service, tenant_id, le) (
     rate(contextiq_request_duration_seconds_bucket[5m])
   ))
   ```
2. Check for slow database queries using `pg_stat_statements` or OpenSearch slow logs.
3. Inspect Kafka consumer lag for the affected service topic.
4. Verify CPU and memory utilisation:
   ```bash
   kubectl top pods -n contextiq -l app=<service>
   ```
5. Look for GC pressure or thread-pool exhaustion in application logs.

---

## Remediation

- Scale the service horizontally if CPU/memory-bound:
  ```bash
  kubectl scale deployment/<service> -n contextiq --replicas=<n>
  ```
- If database-related, review and optimise slow queries or increase connection pool size.
- If Kafka lag is high, check consumer group health and consider partition rebalancing.

---

## Escalation

If p95 latency remains above 3 s after 30 minutes of investigation, escalate to the **Platform SRE on-call** and open a P2 incident.
