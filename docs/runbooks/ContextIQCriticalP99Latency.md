# Runbook: ContextIQCriticalP99Latency

**Alert:** `ContextIQCriticalP99Latency`
**Severity:** critical
**Team:** platform-sre

---

## Impact

The 99th-percentile request duration for a service has exceeded **10 seconds** for at least 2 minutes. Near-timeout conditions are occurring for the slowest requests, risking cascading failures and client-side timeouts.

---

## Diagnosis Steps

1. Identify the affected service and tenant:
   ```promql
   histogram_quantile(0.99, sum by (service, tenant_id, le) (
     rate(contextiq_request_duration_seconds_bucket[5m])
   ))
   ```
2. Check for long-running transactions or locks in PostgreSQL:
   ```sql
   SELECT pid, query, state, wait_event_type, now() - pg_stat_activity.query_start AS duration
   FROM pg_stat_activity
   WHERE state != 'idle'
   ORDER BY duration DESC
   LIMIT 20;
   ```
3. Examine distributed traces in Jaeger for the slowest request spans.
4. Verify Istio circuit-breaker and retry policies are not masking upstream failures.
5. Check if Vault token renewal is blocking secret fetches.

---

## Remediation

- Terminate blocking database sessions if safe to do so.
- If Vault-related, renew service account tokens:
  ```bash
  vault token renew -accessor <accessor>
  ```
- Enable temporary request shedding via Istio `VirtualService` retries/timeouts if cascading risk is high.

---

## Escalation

This is a critical alert. Page the **Platform SRE on-call** immediately via PagerDuty and open a P1 incident. Bridge the on-call database team if PostgreSQL locks are confirmed.
