# TASK-US050-04 — PgBouncer Connection Pooling and PostgreSQL Tuning

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US050-04 |
| User Story | US-050 |
| Epic | EP-DATA-001 — Polyglot Data Store Setup |
| Layer | Infrastructure / Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Deploy PgBouncer in `transaction` pooling mode as a `Deployment` in `contextiq-data` to limit direct connections to PostgreSQL to a maximum of 200 and allow up to 2,000 application-side connections across all service pods (AC-5). PgBouncer authenticates clients using `scram-sha-256` and obtains its own PostgreSQL admin password via Vault Agent sidecar injection. PostgreSQL `postgresql.conf` tuning (shared memory, WAL, autovacuum) is applied via the Bitnami chart's `configuration` value to support the 99.9% uptime target. A `ServiceMonitor` exposes PgBouncer metrics to Prometheus.

## Implementation Details

**Technology:** PgBouncer 1.23+, Bitnami `pgbouncer` Helm chart, Prometheus `pgbouncer_exporter`

**File locations:**
- `helm/charts/pgbouncer/Chart.yaml` — Bitnami pgbouncer wrapper
- `helm/charts/pgbouncer/values.yaml`
- `helm/charts/pgbouncer/values-prod.yaml`
- `k8s/postgres/pgbouncer-config.ini` — full `pgbouncer.ini` reference
- `argocd/apps/services/pgbouncer.yaml`

---

### PgBouncer Helm wrapper

```yaml
# helm/charts/pgbouncer/Chart.yaml
apiVersion: v2
name:        pgbouncer
description: PgBouncer connection pooler for ContextIQ PostgreSQL
type:        application
version:     0.1.0
dependencies:
  - name:       pgbouncer
    version:    "0.x.x"    # Bitnami chart version
    repository: https://charts.bitnami.com/bitnami
```

```yaml
# helm/charts/pgbouncer/values.yaml
pgbouncer:
  replicaCount: 2    # HA: two PgBouncer pods behind a ClusterIP Service

  # Vault Agent injects PostgreSQL admin password at startup (TASK-US047-03)
  podAnnotations:
    vault.hashicorp.com/agent-inject:                    "true"
    vault.hashicorp.com/role:                            "mcp-gateway"
    vault.hashicorp.com/agent-pre-populate-only:         "true"
    vault.hashicorp.com/agent-inject-secret-postgres:    "database/postgres/creds/mcp-gateway"
    vault.hashicorp.com/agent-inject-template-postgres: |
      {{- with secret "database/postgres/creds/mcp-gateway" -}}
      export PGBOUNCER_AUTH_USER_PASSWORD="{{ .Data.password }}"
      {{- end }}

  # pgbouncer.ini settings
  postgresql:
    host:     postgresql.contextiq-data.svc.cluster.local
    port:     5432
    database: contextiq

  config:
    # AC-5: transaction pooling — best latency-per-connection trade-off for FastAPI async workloads
    poolMode:             transaction
    # AC-5: maximum 200 server-side connections to PostgreSQL
    maxClientConn:        2000    # application-facing: up to 2000 client connections
    defaultPoolSize:      40      # per-database pool: 40 server connections × 5 databases = 200 max
    minPoolSize:          5       # keep warm connections ready
    reservePoolSize:      10      # emergency connections for burst above defaultPoolSize
    reservePoolTimeout:   5       # seconds before returning error if reserve pool exhausted

    # Authentication: clients authenticate with the same Vault-issued credentials
    authType:             scram-sha-256
    authFile:             /etc/pgbouncer/userlist.txt

    # Timeouts
    serverConnectTimeout: 10
    serverIdleTimeout:    600     # reclaim idle server connections after 10 min
    clientIdleTimeout:    300     # disconnect idle client connections after 5 min
    queryTimeout:         0       # no per-query timeout (enforced at application layer)

    # Logging — structured for Loki forwarding
    logConnections:       1
    logDisconnections:    1
    logPoolerErrors:      1
    statsUsers:           pgbouncer_monitor    # read-only stats access for Prometheus exporter

  resources:
    requests: { cpu: "250m", memory: "256Mi" }
    limits:   { cpu: "1",    memory: "512Mi" }

  metrics:
    enabled: true          # pgbouncer_exporter sidecar
    serviceMonitor:
      enabled:   true
      namespace: contextiq-observability
      labels:
        app.kubernetes.io/part-of: contextiq

  # HPA: scale PgBouncer pods under high connection load
  autoscaling:
    enabled:     true
    minReplicas: 2
    maxReplicas: 6
    targetCPUUtilizationPercentage: 70
```

```yaml
# helm/charts/pgbouncer/values-prod.yaml
pgbouncer:
  replicaCount: 3
  config:
    maxClientConn:    5000
    defaultPoolSize:  60    # 60 × 3 PgBouncer replicas = up to 180 server connections (under 200 cap)
  resources:
    requests: { cpu: "500m", memory: "512Mi" }
    limits:   { cpu: "2",    memory: "1Gi" }
```

---

### Reference `pgbouncer.ini`

```ini
# k8s/postgres/pgbouncer-config.ini
# Reference configuration — actual values managed by Helm chart above.
# Committed for documentation and manual testing purposes.
[databases]
contextiq = host=postgresql.contextiq-data.svc.cluster.local port=5432 dbname=contextiq

[pgbouncer]
pool_mode              = transaction
max_client_conn        = 2000
default_pool_size      = 40
min_pool_size          = 5
reserve_pool_size      = 10
reserve_pool_timeout   = 5
auth_type              = scram-sha-256
auth_file              = /etc/pgbouncer/userlist.txt
listen_addr            = 0.0.0.0
listen_port            = 5432
# AC-5: enforce connection limit to PostgreSQL
server_connect_timeout = 10
server_idle_timeout    = 600
client_idle_timeout    = 300
log_connections        = 1
log_disconnections     = 1
log_pooler_errors      = 1
stats_users            = pgbouncer_monitor
```

---

### PostgreSQL `postgresql.conf` tuning (applied via Bitnami chart `configuration`)

```yaml
# Addition to helm/charts/postgresql/values.yaml  primary.configuration block:
# (Replace the configuration block in TASK-US050-01 with this expanded version)
primary:
  configuration: |
    # Connection limits — PgBouncer fronts application connections;
    # PostgreSQL only sees PgBouncer's pool connections (max 200)
    max_connections      = 250      # headroom: 200 PgBouncer + 50 direct admin/monitoring

    # Memory: tune for 8-16 GB node
    shared_buffers         = 2GB    # 25% of 8 GB RAM
    effective_cache_size   = 6GB    # estimate of OS + PG cache
    work_mem               = 32MB   # per sort/hash; 250 conns × 32 MB worst-case
    maintenance_work_mem   = 512MB  # VACUUM, CREATE INDEX

    # Checkpoint / WAL
    wal_level              = replica
    max_wal_senders        = 5
    wal_keep_size          = 512MB
    checkpoint_completion_target = 0.9
    checkpoint_timeout     = 10min

    # Autovacuum: aggressive settings for high-write tables (audit_log, execution_trace_index)
    autovacuum_vacuum_scale_factor    = 0.05    # vacuum when 5% of table is dead rows
    autovacuum_analyze_scale_factor   = 0.02
    autovacuum_vacuum_cost_delay      = 2ms     # don't throttle autovacuum heavily

    # Logging — structured JSON for Loki ingestion
    log_destination        = stderr
    logging_collector      = off     # let K8s collect stdout/stderr
    log_min_duration_statement = 500 # log queries > 500 ms
    log_checkpoints        = on
    log_lock_waits         = on

    # Connection — AC-5: 99.9% uptime requires fast failover
    hot_standby            = on
    wal_receiver_timeout   = 30s
    recovery_min_apply_delay = 0

    # SSL — TLS 1.3 (TASK-US048-02)
    ssl                    = on
    ssl_min_protocol_version = 'TLSv1.3'
```

---

### Application database URL: point services at PgBouncer

All application services connect via PgBouncer, not directly to PostgreSQL:

```python
# src/data/database.py  (update DSN host)
# The DATABASE_URL is provided by Vault Agent (/vault/secrets/postgres.env)
# and sourced in the container entrypoint. Application code reads it from the
# environment; the host points to PgBouncer, not PostgreSQL directly.
#
# Example DATABASE_URL format:
#   postgresql+asyncpg://<dynamic_user>:<dynamic_pass>@pgbouncer.contextiq-data.svc.cluster.local:5432/contextiq?ssl=require
#
# Note: PgBouncer transaction mode is incompatible with:
#   - LISTEN/NOTIFY (use direct connection for pub/sub if needed)
#   - prepared statements (set statement_cache_size=0 in asyncpg connect_args)

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
import os

def create_engine() -> AsyncEngine:
    url = os.environ["DATABASE_URL"]
    return create_async_engine(
        url,
        pool_size=5,           # small pool per pod — PgBouncer aggregates across pods
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,    # required for PgBouncer transaction mode
            "ssl": "require",
        },
    )
```

---

### ArgoCD Application

```yaml
# argocd/apps/services/pgbouncer.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: pgbouncer
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://charts.bitnami.com/bitnami
    chart:          pgbouncer
    targetRevision: "0.x.x"
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-data
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

## Acceptance Criteria

- [ ] `kubectl get deployment pgbouncer -n contextiq-data` shows `READY 2/2` (AC-5)
- [ ] `psql "host=pgbouncer.contextiq-data.svc.cluster.local port=5432 dbname=contextiq" -c "SHOW pools;"` shows `pool_mode=transaction` (AC-5)
- [ ] `psql "host=postgresql.contextiq-data.svc.cluster.local" -c "SHOW max_connections;"` returns `250` (AC-5)
- [ ] Under load test (200 concurrent connections to PgBouncer), `psql -c "SELECT count(*) FROM pg_stat_activity;"` on PostgreSQL shows ≤ 200 active backend connections (AC-5)
- [ ] `statement_cache_size=0` set in `create_async_engine` — verified by `psql -c "SHOW prepared_transactions;"` returning 0 rows (PgBouncer transaction mode compatible)
- [ ] Prometheus query `pgbouncer_pools_server_active_connections` visible in Grafana (AC-5)

## Dependencies

- TASK-US050-01 — PostgreSQL must be running as the PgBouncer backend
- TASK-US047-02 — Vault `database/postgres/creds/mcp-gateway` role must exist
- TASK-US047-03 — Vault Agent Injector running; `pgbouncer` ServiceAccount bound to `mcp-gateway` Vault role

## Definition of Done

- [ ] `helm install pgbouncer bitnami/pgbouncer -n contextiq-data -f values.yaml -f values-prod.yaml` completes
- [ ] All application services updated to use `pgbouncer.contextiq-data.svc.cluster.local` as database host
- [ ] `create_async_engine` updated with `statement_cache_size: 0` in `connect_args`
