# Runbook: ContextIQEntityExtractionDLQNonEmpty

**Alert:** `ContextIQEntityExtractionDLQNonEmpty`
**Severity:** warning
**Team:** knowledge-platform

---

## Impact

More than **50 entity or chunk processing errors** have accumulated in a 15-minute window for a tenant. Knowledge graph population is falling behind; entity extraction results may be incomplete or missing, degrading RAG retrieval quality.

---

## Diagnosis Steps

1. Identify the affected tenant:
   ```promql
   sum by (tenant_id) (
     increase(contextiq_errors_total{endpoint=~".*entity.*|.*chunk.*"}[15m])
   )
   ```
2. Check the Kafka dead-letter topic for failed messages:
   ```bash
   kubectl exec -n contextiq deploy/kafka -- \
     kafka-console-consumer.sh \
       --bootstrap-server kafka:9092 \
       --topic contextiq.entity-extraction.dlq \
       --from-beginning \
       --max-messages 20
   ```
3. Inspect entity extraction service logs:
   ```bash
   kubectl logs -n contextiq -l app=indexing-service --since=20m | grep -i "entity\|chunk\|extract"
   ```
4. Verify the NLP model endpoint (if external) is reachable and returning valid responses.
5. Check for malformed or oversized documents that may be triggering parsing failures.

---

## Remediation

- Replay messages from the DLQ after fixing the root cause:
  ```bash
  kubectl exec -n contextiq deploy/indexing-service -- \
    python manage.py replay_dlq --topic entity-extraction --tenant <tenant_id>
  ```
- If a specific document is causing repeated failures, quarantine it and re-queue the rest.
- Scale the indexing service if throughput is the constraint:
  ```bash
  kubectl scale deployment/indexing-service -n contextiq --replicas=<n>
  ```

---

## Escalation

If the DLQ continues to grow after 30 minutes, escalate to the **Knowledge Platform team lead** and assess whether the affected tenant needs to be notified about delayed knowledge graph updates.
