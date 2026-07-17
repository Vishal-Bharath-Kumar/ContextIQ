# Runbook: ContextIQConnectorFailureRate

**Alert:** `ContextIQConnectorFailureRate`
**Severity:** warning
**Team:** platform-sre

---

## Impact

More than **10%** of knowledge source sync requests (`/v1/knowledge-sources/*`) are failing for at least 5 minutes. Tenant data ingestion is degraded; knowledge graph updates and RAG context may become stale.

---

## Diagnosis Steps

1. Identify the affected service and tenant:
   ```promql
   sum by (service, tenant_id) (
     rate(contextiq_errors_total{endpoint=~"/v1/knowledge-sources.*"}[5m])
   )
   / sum by (service, tenant_id) (
     rate(contextiq_requests_total{endpoint=~"/v1/knowledge-sources.*"}[5m])
   )
   ```
2. Check connector-specific error logs:
   ```bash
   kubectl logs -n contextiq -l app=indexing-service --since=15m | grep "knowledge-source"
   ```
3. Verify Vault availability and that connector secrets have not expired:
   ```bash
   vault status
   vault kv get secret/contextiq/connectors/<connector-type>
   ```
4. Test external source reachability (e.g., Confluence, SharePoint, S3) from within the cluster.
5. Check the sync job queue in PostgreSQL:
   ```sql
   SELECT status, count(*) FROM sync_jobs GROUP BY status;
   ```

---

## Remediation

- Rotate and re-provision expired connector credentials in Vault.
- Re-trigger failed sync jobs:
  ```bash
  kubectl exec -n contextiq deploy/indexing-service -- python manage.py retry_failed_sync_jobs
  ```
- If an external source is unreachable, engage the tenant to verify credentials and network access.

---

## Escalation

If failure rate remains above 10% after 30 minutes, escalate to the **Knowledge Platform team** and notify the affected tenant(s) via the status page.
