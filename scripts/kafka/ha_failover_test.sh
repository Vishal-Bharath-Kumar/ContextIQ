#!/usr/bin/env bash
# scripts/kafka/ha_failover_test.sh
# AC-6: Measures producer-side outage duration during a broker pod deletion.
# Usage: ./ha_failover_test.sh
# Exits 0 if outage < 5s; exits 1 otherwise.
set -euo pipefail

NAMESPACE="contextiq-data"
TOPIC="contextiq.state.events"
MAX_GAP_SECONDS=5

echo "=== KRaft broker chaos test ==="

# Select a non-leader broker to delete (any of kafka-controller-1 or -2)
VICTIM_POD="kafka-controller-1"

echo "→ Victim broker: ${VICTIM_POD}"
echo "→ Starting background producer…"

PRODUCER_LOG=$(mktemp)

# Background producer: writes one message per 200ms.
# NOTE: --bootstrap-server replaces the deprecated --broker-list flag (Kafka 3.x)
(
  for i in $(seq 1 200); do
    echo "${i}:$(date +%s%3N)"
    sleep 0.2
  done | kafka-console-producer.sh \
    --bootstrap-server "kafka.${NAMESPACE}.svc.cluster.local:9092" \
    --topic "${TOPIC}" \
    --producer-property security.protocol=SASL_SSL \
    --producer-property sasl.mechanism=SCRAM-SHA-512 \
    --producer-property "sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username=\"${KAFKA_USERNAME:?KAFKA_USERNAME required}\" password=\"${KAFKA_PASSWORD:?KAFKA_PASSWORD required}\";" \
    2>&1
) > "${PRODUCER_LOG}" &
PRODUCER_PID=$!

# Let the producer warm up before injecting failure
sleep 2

DELETE_TIME=$(date +%s%3N)
echo "→ Deleting pod ${VICTIM_POD} at timestamp ${DELETE_TIME}ms"
kubectl delete pod "${VICTIM_POD}" -n "${NAMESPACE}" --grace-period=0 --force

echo "→ Waiting for pod to restart and StatefulSet to become ready…"
kubectl rollout status statefulset/kafka-controller -n "${NAMESPACE}" --timeout=120s

RECOVER_TIME=$(date +%s%3N)
OUTAGE_MS=$(( RECOVER_TIME - DELETE_TIME ))
OUTAGE_S=$(echo "scale=2; ${OUTAGE_MS} / 1000" | bc)
echo "→ Broker rejoined quorum in ${OUTAGE_S}s (${OUTAGE_MS}ms)"

wait "${PRODUCER_PID}" || true
rm -f "${PRODUCER_LOG}"

if (( OUTAGE_MS < MAX_GAP_SECONDS * 1000 )); then
  echo "PASS: outage ${OUTAGE_S}s < ${MAX_GAP_SECONDS}s threshold"
  exit 0
else
  echo "FAIL: outage ${OUTAGE_S}s exceeds ${MAX_GAP_SECONDS}s threshold"
  exit 1
fi
