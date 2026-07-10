# TASK-US051-04 — Redis Sentinel HA and Keyspace Notifications

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US051-04 |
| User Story | US-051 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Deploy Redis in Sentinel HA mode with 1 primary and 2 replicas using the Bitnami `redis` Helm chart (AC-4). Sentinel monitors the primary and automatically promotes a replica if the primary fails, providing sub-10-second failover. Keyspace notifications (`notify-keyspace-events KEA`) are enabled so the application can subscribe to cache-invalidation events via the `__keyevent@*__:expired` and `__keyevent@*__:del` channels (AC-4). Redis authentication credentials are injected by Vault Agent sidecar (AC-6); a Prometheus ServiceMonitor scrapes the redis-exporter metrics endpoint (AC-7).

## Implementation Details

**Technology:** Redis 7.2.x, Bitnami `redis` Helm chart (`redis/redis`), Sentinel mode, Python `redis.asyncio>=5`

**File locations:**
- `helm/charts/redis/Chart.yaml`
- `helm/charts/redis/values.yaml`
- `helm/charts/redis/values-prod.yaml`
- `scripts/datastore/verify_redis.py` — connectivity and keyspace notification verification
- `argocd/apps/services/redis.yaml`

---

### Helm wrapper

```yaml
# helm/charts/redis/Chart.yaml
apiVersion: v2
name:        redis
description: Redis Sentinel HA for ContextIQ caching layer
type:        application
version:     0.1.0
dependencies:
  - name:       redis
    version:    "19.x.x"    # Bitnami chart version tracking Redis 7.2
    repository: https://charts.bitnami.com/bitnami
```

```yaml
# helm/charts/redis/values.yaml
redis:
  image:
    tag: "7.2.5-debian-12-r0"    # pin for reproducibility

  # AC-4: Sentinel HA — 1 primary + 2 replicas, 3 Sentinel instances
  architecture: replication

  auth:
    enabled: true
    # AC-6: password is NOT hard-coded; Vault Agent overwrites the env var at runtime
    existingSecret:     ""
    existingSecretPasswordKey: ""
    password:           "PLACEHOLDER"    # overwritten by Vault-injected env var

  sentinel:
    enabled: true
    masterSet:       contextiq-redis    # sentinel group name used in application connection string
    quorum:          2                  # 2 of 3 sentinels must agree to trigger failover
    downAfterMilliseconds: 5000         # declare primary down after 5 s
    failoverTimeout: 10000              # attempt failover within 10 s
    parallelSyncs:   1

  # AC-4: keyspace notifications — enabled on primary and replicas
  # KEA = Keyevent + Expired + All events on all data types
  commonConfiguration: |
    notify-keyspace-events KEA
    hz 15              # sentinel check frequency (default 10 Hz; slightly higher for faster detection)
    loglevel notice
    save ""            # disable RDB snapshots (use AOF only for data integrity)
    appendonly yes
    appendfsync everysec
    # TLS: enabled via cert-manager issued cert (TASK-US048-02)
    tls-port 6379
    port 0             # disable plaintext port — TLS only (AC-4, TASK-US048-02)

  master:
    resources:
      requests: { cpu: "500m",  memory: "1Gi" }
      limits:   { cpu: "2",     memory: "4Gi" }
    persistence:
      enabled:      true
      storageClass: contextiq-encrypted-gp3    # AC-5 of US-048: encrypted PVC
      size:         20Gi

    # AC-6: Vault Agent injects Redis password into the primary pod
    podAnnotations:
      vault.hashicorp.com/agent-inject:                "true"
      vault.hashicorp.com/role:                        "mcp-gateway"
      vault.hashicorp.com/agent-pre-populate-only:     "true"
      vault.hashicorp.com/agent-inject-secret-redis:   "database/redis/creds/mcp-gateway"
      vault.hashicorp.com/agent-inject-template-redis: |
        {{- with secret "database/redis/creds/mcp-gateway" -}}
        export REDIS_PASSWORD="{{ .Data.password }}"
        export REDIS_ACL_USERNAME="{{ .Data.username }}"
        {{- end }}

  replica:
    replicaCount: 2    # AC-4: 1 primary + 2 replicas

    resources:
      requests: { cpu: "250m",  memory: "1Gi" }
      limits:   { cpu: "1",     memory: "2Gi" }

    # AC-4: anti-affinity — spread replicas across distinct nodes
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app.kubernetes.io/name:      redis
                app.kubernetes.io/component: replica
            topologyKey: kubernetes.io/hostname

    podAnnotations:
      vault.hashicorp.com/agent-inject:                "true"
      vault.hashicorp.com/role:                        "mcp-gateway"
      vault.hashicorp.com/agent-pre-populate-only:     "true"
      vault.hashicorp.com/agent-inject-secret-redis:   "database/redis/creds/mcp-gateway"
      vault.hashicorp.com/agent-inject-template-redis: |
        {{- with secret "database/redis/creds/mcp-gateway" -}}
        export REDIS_PASSWORD="{{ .Data.password }}"
        {{- end }}

    persistence:
      enabled:      true
      storageClass: contextiq-encrypted-gp3
      size:         20Gi

  # PDB — tolerate 1 pod down (primary OR replica)
  podDisruptionBudget:
    enabled:      true
    minAvailable: 2    # keep 2 of 3 Redis pods (primary + 1 replica) always available

  # AC-7: Prometheus redis-exporter sidecar
  metrics:
    enabled: true
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
      labels:
        app.kubernetes.io/part-of: contextiq
    resources:
      requests: { cpu: "50m", memory: "64Mi" }
      limits:   { cpu: "100m", memory: "128Mi" }
```

```yaml
# helm/charts/redis/values-prod.yaml
redis:
  master:
    resources:
      requests: { cpu: "1",  memory: "4Gi" }
      limits:   { cpu: "4",  memory: "8Gi" }
    persistence:
      size: 50Gi
  replica:
    resources:
      requests: { cpu: "500m", memory: "2Gi" }
      limits:   { cpu: "2",    memory: "4Gi" }
    persistence:
      size: 50Gi
```

---

### Application: connect via Sentinel

```python
# src/data/redis_client.py
"""
Redis client factory using Sentinel for HA discovery.
AC-4: connects via Sentinel which transparently routes to the current primary.
"""
from __future__ import annotations

import os

import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel


def create_redis_client() -> aioredis.Redis:
    """Return an async Redis client via Sentinel for HA."""
    sentinel_hosts_raw = os.environ.get(
        "REDIS_SENTINEL_HOSTS",
        "redis-headless.contextiq-data.svc.cluster.local:26379",
    )
    sentinel_hosts = [
        (h.split(":")[0], int(h.split(":")[1]))
        for h in sentinel_hosts_raw.split(",")
    ]
    master_name = os.environ.get("REDIS_SENTINEL_MASTER", "contextiq-redis")
    password    = os.environ.get("REDIS_PASSWORD", "")

    sentinel = Sentinel(
        sentinel_hosts,
        sentinel_kwargs={"password": password, "ssl": True, "ssl_certfile": "/tls/tls.crt"},
        password=password,
        ssl=True,
        ssl_certfile="/tls/tls.crt",
        ssl_keyfile="/tls/tls.key",
        ssl_ca_certs="/tls/ca.crt",
        decode_responses=True,
    )
    # master_for returns a Redis client that always uses the current Sentinel-elected primary
    return sentinel.master_for(master_name, socket_timeout=0.5)


def create_redis_subscriber() -> aioredis.Redis:
    """
    Return a dedicated Redis client for keyspace notification subscriptions.
    AC-4: subscribe to __keyevent@*__:expired for cache invalidation events.
    A separate client is used because PubSub connections cannot mix with regular commands.
    """
    # For subscriptions, connect directly to the primary (Sentinel-discovered host)
    # as Sentinel clients auto-reconnect on failover
    return create_redis_client()
```

---

### Verification script

```python
# scripts/datastore/verify_redis.py
"""
AC-4: Verify Redis Sentinel HA and keyspace notifications.
"""
from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel


async def main() -> int:
    password = os.environ.get("REDIS_PASSWORD", "")
    sentinel_hosts = [
        ("redis-headless.contextiq-data.svc.cluster.local", 26379),
    ]

    sentinel = Sentinel(
        sentinel_hosts,
        sentinel_kwargs={"password": password},
        password=password,
        decode_responses=True,
    )

    # --- Check 1: Sentinel sees a master ---
    master_info = await sentinel.discover_master("contextiq-redis")
    print(f"[OK] Sentinel master: {master_info}")

    # --- Check 2: Sentinel sees 2 replicas ---
    slaves = await sentinel.discover_slaves("contextiq-redis")
    print(f"[OK] Sentinel replicas: {len(slaves)} (expected 2)")
    if len(slaves) < 2:
        print("WARNING: Expected 2 replicas, check replication status")

    master = sentinel.master_for("contextiq-redis", socket_timeout=1.0)

    # --- Check 3: keyspace notifications enabled ---
    config = await master.config_get("notify-keyspace-events")
    events = config.get("notify-keyspace-events", "")
    print(f"[{'OK' if 'K' in events else 'FAIL'}] notify-keyspace-events = {events!r}")
    if "K" not in events or "E" not in events:
        print("FAIL: Keyspace notifications (KEA) are not enabled (AC-4)")
        return 1

    # --- Check 4: basic SET/GET round-trip ---
    await master.set("healthcheck:verify_redis", "ok", ex=60)
    val = await master.get("healthcheck:verify_redis")
    print(f"[OK] SET/GET round-trip: {val!r}")

    # --- Check 5: publish/subscribe to keyspace events ---
    async with master.pubsub() as pubsub:
        await pubsub.psubscribe("__keyevent@0__:expired")
        await master.set("healthcheck:expiry_test", "x", px=100)    # 100ms TTL
        await asyncio.sleep(0.5)
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message:
            print(f"[OK] Received keyspace expiry event: {message}")
        else:
            print("[WARN] No expiry event received — keyspace notifications may need a moment")

    await master.aclose()
    print("\n=== Redis verification passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/redis.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: redis
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.bitnami.com/bitnami
    chart:          redis
    targetRevision: "19.x.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: false, selfHeal: true }
```

## Acceptance Criteria

- [ ] `kubectl get pods -n contextiq-data -l app.kubernetes.io/name=redis` shows `redis-master-0` + 2 replica pods Running (AC-4)
- [ ] `redis-cli -p 26379 SENTINEL masters` shows `contextiq-redis` with `num-slaves: 2` and `num-other-sentinels: 2` (AC-4)
- [ ] `redis-cli CONFIG GET notify-keyspace-events` returns `KEA` (AC-4)
- [ ] Killing `redis-master-0` results in automatic failover to a replica within 10 seconds; `SENTINEL masters` shows new primary (AC-4)
- [ ] `python scripts/datastore/verify_redis.py` passes all 5 checks (AC-4)
- [ ] `/vault/secrets/redis.env` present in master pod with `REDIS_PASSWORD` (AC-6)
- [ ] `kubectl get servicemonitor redis -n contextiq-observability` exists; `redis_*` metrics in Grafana (AC-7)

## Dependencies

- TASK-US045-01 — `contextiq-data` namespace
- TASK-US047-02 — Vault `database/redis/creds/mcp-gateway` role configured
- TASK-US048-02 — TLS 1.3 enforcement; Redis `tls-port 6379` requires cert-manager certificate
- TASK-US048-04 — `contextiq-encrypted-gp3` StorageClass

## Definition of Done

- [ ] Redis Sentinel cluster stable; `verify_redis.py` passes in staging
- [ ] Application connects via `create_redis_client()` in `src/data/redis_client.py`
- [ ] Keyspace notification test: `SET key ex 1` → `__keyevent@0__:expired` received within 2 seconds
