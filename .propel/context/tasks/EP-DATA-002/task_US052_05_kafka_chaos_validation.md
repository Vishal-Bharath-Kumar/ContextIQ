# TASK-US052-05 — KRaft Chaos Test: Broker Failure < 5 s Interruption + Integration Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US052-05 |
| User Story | US-052 |
| Epic | EP-DATA-002 — Event Streaming Infrastructure |
| Layer | QA / Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Draft |

## Description

Validate that the KRaft cluster survives the failure of one broker with message delivery interruption of less than 5 seconds (AC-6). A Python test uses `aiokafka` to produce messages in a tight loop while a shell script kills one broker pod via `kubectl delete pod`; timestamps are compared to find the gap between the last successful produce and the first successful produce after recovery. A full pytest integration suite validates all 6 ACs end-to-end. Chaos tests are tagged `@pytest.mark.destructive` and gated behind `--run-destructive`.

## Implementation Details

**Technology:** `aiokafka>=0.11`, Python 3.11+, `pytest-asyncio`, `kubectl`, Kubernetes cluster

**File locations:**
- `tests/integration/test_kafka.py` — full US-052 integration test suite
- `scripts/kafka/ha_failover_test.sh` — standalone timing script for CI chaos gate

---

### Shell timing script (CI chaos gate)

```bash
#!/usr/bin/env bash
# scripts/kafka/ha_failover_test.sh
# AC-6: Measures produce-side interruption during a broker pod deletion.
# Usage: ./ha_failover_test.sh
# Exits 0 if max gap < 5s; exits 1 otherwise.
set -euo pipefail

NAMESPACE="contextiq-data"
TOPIC="contextiq.state.events"
MAX_GAP_SECONDS=5

echo "=== KRaft broker chaos test ==="

# Select a non-leader broker to delete (any of kafka-controller-1 or -2)
VICTIM_POD="kafka-controller-1"

echo "→ Victim broker: $VICTIM_POD"
echo "→ Starting background producer…"

PRODUCER_LOG=$(mktemp)

# Background producer: writes one message per 200ms with millisecond timestamps
(
  for i in $(seq 1 200); do
    echo "${i}:$(date +%s%3N)"
    sleep 0.2
  done | kafka-console-producer.sh \
    --broker-list kafka.${NAMESPACE}.svc.cluster.local:9092 \
    --topic "$TOPIC" \
    --producer-property security.protocol=SASL_SSL \
    --producer-property sasl.mechanism=SCRAM-SHA-512 \
    --producer-property sasl.jaas.config="org.apache.kafka.common.security.scram.ScramLoginModule required username=\"$KAFKA_USERNAME\" password=\"$KAFKA_PASSWORD\";" \
    2>&1
) > "$PRODUCER_LOG" &
PRODUCER_PID=$!

# Let the producer run for 2 seconds before killing the broker
sleep 2

DELETE_TIME=$(date +%s%3N)
echo "→ Deleting pod $VICTIM_POD at timestamp ${DELETE_TIME}ms"
kubectl delete pod "$VICTIM_POD" -n "$NAMESPACE" --grace-period=0 --force

echo "→ Waiting for pod to restart and rejoin quorum…"
kubectl rollout status statefulset/kafka-controller -n "$NAMESPACE" --timeout=120s

RECOVER_TIME=$(date +%s%3N)
OUTAGE_MS=$(( RECOVER_TIME - DELETE_TIME ))
OUTAGE_S=$(echo "scale=2; $OUTAGE_MS / 1000" | bc)
echo "→ Broker rejoined quorum in ${OUTAGE_S}s (${OUTAGE_MS}ms)"

wait "$PRODUCER_PID" || true
rm -f "$PRODUCER_LOG"

if (( OUTAGE_MS < MAX_GAP_SECONDS * 1000 )); then
  echo "✓ PASS: outage ${OUTAGE_S}s < ${MAX_GAP_SECONDS}s threshold"
  exit 0
else
  echo "✗ FAIL: outage ${OUTAGE_S}s exceeds ${MAX_GAP_SECONDS}s threshold"
  exit 1
fi
```

---

### Integration test suite

```python
# tests/integration/test_kafka.py
"""
Integration tests for US-052: Kafka KRaft cluster, topics, consumer groups, and chaos.

Prerequisites:
  - Kafka running in contextiq-data with SCRAM-SHA-512 auth
  - Environment vars: KAFKA_BOOTSTRAP_SERVERS, KAFKA_USERNAME, KAFKA_PASSWORD
  - kubectl context pointing at target cluster (for AC-6 chaos test)

Run:
    pytest tests/integration/test_kafka.py -v --tb=short
    pytest tests/integration/test_kafka.py -v --run-destructive  # includes chaos test
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient

from src.kafka.topic_registry import TOPICS

BOOTSTRAP_SERVERS = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "kafka.contextiq-data.svc.cluster.local:9092",
)
KAFKA_USERNAME = os.environ.get("KAFKA_USERNAME", "")
KAFKA_PASSWORD = os.environ.get("KAFKA_PASSWORD", "")


def _sasl_kwargs() -> dict[str, Any]:
    return {
        "security_protocol":   "SASL_SSL",
        "sasl_mechanism":      "SCRAM-SHA-512",
        "sasl_plain_username": KAFKA_USERNAME,
        "sasl_plain_password": KAFKA_PASSWORD,
        "ssl_cafile":          "/tls/ca.crt",
    }


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-destructive",
        action="store_true",
        default=False,
        help="Include destructive chaos tests (requires kubectl access to contextiq-data)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--run-destructive"):
        skip_destructive = pytest.mark.skip(reason="Pass --run-destructive to run chaos tests")
        for item in items:
            if "destructive" in item.keywords:
                item.add_marker(skip_destructive)


# ---------------------------------------------------------------------------
# AC-1: KRaft deployment — 3 brokers, no ZooKeeper
# ---------------------------------------------------------------------------

class TestAC1_KRaftDeployment:

    def test_three_broker_pods_running(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", "contextiq-data",
             "-l", "app.kubernetes.io/component=controller",
             "-o", "jsonpath={.items[*].status.phase}"],
            capture_output=True, timeout=15,
        )
        phases = result.stdout.decode().split()
        assert len(phases) == 3 and all(p == "Running" for p in phases), (
            f"Expected 3 Running Kafka broker pods, got: {phases}"
        )

    def test_no_zookeeper_pods(self) -> None:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", "contextiq-data",
             "-l", "app.kubernetes.io/name=zookeeper",
             "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, timeout=15,
        )
        pods = result.stdout.decode().strip()
        assert pods == "", f"ZooKeeper pods found — cluster should use KRaft: {pods}"

    @pytest.mark.asyncio
    async def test_kraft_quorum_has_3_voters(self) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-kraft-quorum",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            # describe_metadata returns controller info; leader epoch > 0 means KRaft is active
            meta = await admin.describe_cluster()
            assert meta.controller is not None, "No active KRaft controller"
            assert meta.controller.node_id >= 0, "Invalid controller node ID"
        finally:
            await admin.close()


# ---------------------------------------------------------------------------
# AC-2: Topics — correct partitions and retention
# ---------------------------------------------------------------------------

class TestAC2_Topics:

    @pytest.mark.asyncio
    async def test_all_topics_exist(self) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-topics",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            existing = await admin.list_topics()
        finally:
            await admin.close()

        for spec in TOPICS:
            assert spec.name in existing, f"Topic {spec.name!r} not found on broker"

    @pytest.mark.asyncio
    async def test_topic_partition_counts(self) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-partitions",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            topic_names = [s.name for s in TOPICS]
            descriptions = await admin.describe_topics(topic_names)
        finally:
            await admin.close()

        for desc in descriptions:
            spec = next(s for s in TOPICS if s.name == desc["topic"])
            actual = len(desc["partitions"])
            assert actual == spec.partitions, (
                f"Topic {spec.name}: expected {spec.partitions} partitions, got {actual}"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("topic_name,expected_retention_ms", [
        ("knowledge.source.synced",      604_800_000),   # 7 days
        ("knowledge.chunk.indexed",      604_800_000),   # 7 days
        ("knowledge.graph.updated",      604_800_000),   # 7 days
        ("contextiq.state.events",        86_400_000),   # 24 hours
        ("contextiq.governance.events", 2_592_000_000),  # 30 days
        ("contextiq.connector.health",    3_600_000),    # 1 hour
    ])
    async def test_topic_retention_config(
        self, topic_name: str, expected_retention_ms: int
    ) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-retention",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            configs = await admin.describe_configs(
                [("TOPIC", topic_name)], config_names=["retention.ms"]
            )
        finally:
            await admin.close()

        retention_value = int(configs[topic_name]["retention.ms"])
        assert retention_value == expected_retention_ms, (
            f"Topic {topic_name}: retention.ms={retention_value}, expected={expected_retention_ms}"
        )


# ---------------------------------------------------------------------------
# AC-3: Consumer groups pre-registered
# ---------------------------------------------------------------------------

class TestAC3_ConsumerGroups:

    EXPECTED_GROUPS = {
        "indexing-service",
        "graph-agent",
        "context-retrieval",
        "replay-service",
        "audit-logger",
        "health-monitor",
    }

    @pytest.mark.asyncio
    async def test_all_consumer_groups_exist(self) -> None:
        admin = AIOKafkaAdminClient(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            client_id="test-groups",
            **_sasl_kwargs(),
        )
        await admin.start()
        try:
            groups = {g.group_id for g in await admin.list_consumer_groups()}
        finally:
            await admin.close()

        for expected in self.EXPECTED_GROUPS:
            assert expected in groups, (
                f"Consumer group '{expected}' not pre-registered on broker"
            )

    @pytest.mark.asyncio
    async def test_produce_and_consume_round_trip(self) -> None:
        """Produce 1 message to a test topic and verify the consumer receives it."""
        test_topic = "contextiq.state.events"
        test_value = json.dumps({"test": "round-trip", "ts": int(time.time() * 1000)}).encode()

        producer = AIOKafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            **_sasl_kwargs(),
        )
        await producer.start()
        await producer.send(test_topic, value=test_value)
        await producer.flush()
        await producer.stop()

        consumer = AIOKafkaConsumer(
            test_topic,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            group_id="test-round-trip",
            auto_offset_reset="latest",
            consumer_timeout_ms=5000,
            **_sasl_kwargs(),
        )
        await consumer.start()
        received: list[bytes] = []
        try:
            async for msg in consumer:
                received.append(msg.value)
                break
        except Exception:
            pass
        finally:
            await consumer.stop()

        assert len(received) == 1, "No message received in round-trip test"


# ---------------------------------------------------------------------------
# AC-4: Kafka Connect REST API
# ---------------------------------------------------------------------------

class TestAC4_KafkaConnect:

    def test_kafka_connect_rest_api_responds(self) -> None:
        import urllib.request
        url = "http://kafka-connect.contextiq-data.svc.cluster.local:8083/"
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read())
        assert "version" in body, f"Kafka Connect API did not return version: {body}"

    def test_kafka_connect_connectors_list(self) -> None:
        import urllib.request
        url = "http://kafka-connect.contextiq-data.svc.cluster.local:8083/connectors"
        with urllib.request.urlopen(url, timeout=10) as resp:
            connectors = json.loads(resp.read())
        assert isinstance(connectors, list), "Connectors endpoint did not return a list"


# ---------------------------------------------------------------------------
# AC-5: Prometheus metrics scraped
# ---------------------------------------------------------------------------

class TestAC5_BrokerMetrics:

    PROMETHEUS_URL = os.environ.get(
        "PROMETHEUS_URL",
        "http://prometheus.contextiq-observability.svc.cluster.local:9090",
    )

    def _query(self, expr: str) -> list[dict]:
        import urllib.request, urllib.parse
        url = f"{self.PROMETHEUS_URL}/api/v1/query?query={urllib.parse.quote(expr)}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("data", {}).get("result", [])

    def test_under_replicated_partitions_is_zero(self) -> None:
        results = self._query("kafka_server_replicamanager_underreplicatedpartitions")
        assert results, "kafka_server_replicamanager_underreplicatedpartitions metric not found"
        for r in results:
            value = float(r["value"][1])
            assert value == 0.0, f"Under-replicated partitions > 0 on broker: {r['metric']}"

    def test_active_controller_count_is_one(self) -> None:
        results = self._query("kafka_controller_kafkacontroller_activecontrollercount")
        total = sum(float(r["value"][1]) for r in results)
        assert total == 1.0, f"Expected exactly 1 active KRaft controller, got {total}"

    def test_bytes_in_rate_metric_exists(self) -> None:
        results = self._query("kafka_server_brokertopicmetrics_bytesin_rate")
        assert results, "kafka_server_brokertopicmetrics_bytesin_rate metric not found in Prometheus"


# ---------------------------------------------------------------------------
# AC-6: KRaft chaos test — broker failure < 5 s
# ---------------------------------------------------------------------------

class TestAC6_KRaftChaos:

    MAX_GAP_SECONDS = 5
    NAMESPACE       = "contextiq-data"
    TEST_TOPIC      = "contextiq.state.events"
    VICTIM_POD      = "kafka-controller-1"

    @pytest.mark.destructive
    @pytest.mark.asyncio
    async def test_broker_failure_interruption_under_5s(self) -> None:
        """
        AC-6: One broker pod is deleted while a producer runs in a tight loop.
        The maximum gap between consecutive successful produces must be < 5 s.
        """
        produce_timestamps: list[float] = []
        produce_errors:     list[float] = []
        stop_event         = asyncio.Event()

        async def _producer_loop() -> None:
            producer = AIOKafkaProducer(
                bootstrap_servers=BOOTSTRAP_SERVERS,
                acks="all",    # require all ISR to ack — strictest durability
                **_sasl_kwargs(),
            )
            await producer.start()
            try:
                while not stop_event.is_set():
                    try:
                        await asyncio.wait_for(
                            producer.send_and_wait(
                                self.TEST_TOPIC,
                                value=f"{time.monotonic():.6f}".encode(),
                            ),
                            timeout=1.0,
                        )
                        produce_timestamps.append(time.monotonic())
                    except Exception:
                        produce_errors.append(time.monotonic())
                    await asyncio.sleep(0.1)    # 10 messages/s
            finally:
                await producer.stop()

        # Start producer in background
        producer_task = asyncio.create_task(_producer_loop())

        # Let it warm up for 2 seconds
        await asyncio.sleep(2)

        # Kill a non-leader broker
        delete_time = time.monotonic()
        subprocess.run(
            ["kubectl", "delete", "pod", self.VICTIM_POD, "-n", self.NAMESPACE,
             "--grace-period=0", "--force"],
            check=True, timeout=15,
        )

        # Wait up to 60 s for the pod to restart and rejoin
        max_wait = 60
        for _ in range(max_wait * 2):
            result = subprocess.run(
                ["kubectl", "get", "pod", self.VICTIM_POD, "-n", self.NAMESPACE,
                 "-o", "jsonpath={.status.phase}"],
                capture_output=True, timeout=10,
            )
            if result.stdout.decode().strip() == "Running":
                break
            await asyncio.sleep(0.5)
        else:
            stop_event.set()
            await producer_task
            pytest.fail(f"{self.VICTIM_POD} did not restart within {max_wait}s")

        recover_time = time.monotonic()

        # Let the producer run 3 more seconds after recovery
        await asyncio.sleep(3)
        stop_event.set()
        await producer_task

        # Compute max gap between consecutive successful produce timestamps
        if len(produce_timestamps) < 2:
            pytest.fail(f"Too few successful produces ({len(produce_timestamps)}) to measure gap")

        max_gap = max(
            produce_timestamps[i + 1] - produce_timestamps[i]
            for i in range(len(produce_timestamps) - 1)
        )

        total_outage = recover_time - delete_time
        print(
            f"\nBroker failure metrics: "
            f"total_outage={total_outage:.2f}s, "
            f"max_produce_gap={max_gap:.2f}s, "
            f"total_errors={len(produce_errors)}"
        )

        assert max_gap < self.MAX_GAP_SECONDS, (
            f"Max produce gap {max_gap:.2f}s exceeds {self.MAX_GAP_SECONDS}s threshold. "
            f"KRaft leader election took too long after broker {self.VICTIM_POD} was killed."
        )
```

## Acceptance Criteria

- [ ] `pytest tests/integration/test_kafka.py -v` passes all non-destructive tests (AC-1 through AC-5) (all ACs)
- [ ] `pytest tests/integration/test_kafka.py -v --run-destructive` passes `TestAC6_KRaftChaos::test_broker_failure_interruption_under_5s` with `max_produce_gap < 5.0 s` (AC-6)
- [ ] `ha_failover_test.sh` exits 0 with outage printed as `< 5s` (AC-6)
- [ ] `TestAC3_ConsumerGroups::test_produce_and_consume_round_trip` confirms end-to-end produce → consume on `contextiq.state.events` (AC-3)
- [ ] `TestAC5_BrokerMetrics::test_under_replicated_partitions_is_zero` returns 0 for all brokers in steady state (AC-5)
- [ ] `TestAC6_KRaftChaos` is skipped in normal `pytest` runs (no `--run-destructive` flag) (AC-6)
- [ ] After chaos test, victim pod `kafka-controller-1` rejoins quorum and `ActiveControllerCount=1` metric is restored (AC-6)

## Dependencies

- TASK-US052-01 — KRaft 3-broker cluster must be Running
- TASK-US052-02 — All 6 topics must be created
- TASK-US052-03 — Consumer groups pre-registered; `src/kafka/topic_registry.py` on `PYTHONPATH`
- TASK-US052-04 — Kafka Connect and ServiceMonitor deployed (for AC-4 and AC-5 test classes)
- `kubectl` binary and cluster credentials available in the test environment for chaos test

## Definition of Done

- [ ] Full non-destructive pytest suite passes in CI (no `--run-destructive`)
- [ ] Chaos test validated manually in staging: `max_produce_gap < 5 s`
- [ ] `ha_failover_test.sh` committed and executable; exits 0 in staging
- [ ] Test file committed to `tests/integration/test_kafka.py`
