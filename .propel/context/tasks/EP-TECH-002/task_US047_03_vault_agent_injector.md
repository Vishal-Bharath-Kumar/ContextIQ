# TASK-US047-03 — Vault Agent Injector Sidecar Configuration for All Services

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US047-03 |
| User Story | US-047 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Annotate every service Deployment so the Vault Agent Injector mutating webhook injects an `agent` init-container and sidecar into each pod (AC-3). The init-container fetches credentials before the application container starts; the sidecar renews leases before the 1-hour TTL expires (AC-4). Credentials are rendered to `/vault/secrets/` as environment-variable-compatible files that the application reads at startup via `envFrom` file source or `env` substitution. Helm chart templates are updated to include the standard Vault annotation stanza, controlled by a `vault.enabled` values flag.

## Implementation Details

**Technology:** Vault Agent Injector 0.28+, Kubernetes annotation-driven sidecar injection, Helm 3.15+

**File locations:**
- `helm/library/contextiq-common/templates/_vault_annotations.tpl` — shared annotation helper
- `helm/charts/mcp-gateway/values.yaml` — add `vault:` stanza
- `helm/charts/agent-worker/values.yaml` — add `vault:` stanza
- `helm/charts/indexing-service/values.yaml` — add `vault:` stanza
- `helm/charts/admin-portal/values.yaml` — add `vault:` stanza (admin-api backend)

---

### Shared Vault annotation helper (common library)

```
{{- /* helm/library/contextiq-common/templates/_vault_annotations.tpl */}}
{{- define "contextiq-common.vault.annotations" -}}
{{- if .Values.vault.enabled }}
vault.hashicorp.com/agent-inject: "true"
vault.hashicorp.com/role: {{ .Values.vault.role | quote }}
vault.hashicorp.com/agent-pre-populate-only: "false"   # keep sidecar for renewal (AC-4)
vault.hashicorp.com/agent-inject-token: "false"        # don't expose the Vault token itself
vault.hashicorp.com/agent-cache-enable: "true"         # agent-side caching for fast renewal
vault.hashicorp.com/agent-cache-use-auto-auth-token: "true"
{{- range .Values.vault.secrets }}
vault.hashicorp.com/agent-inject-secret-{{ .name }}: {{ .vaultPath | quote }}
vault.hashicorp.com/agent-inject-template-{{ .name }}: |
  {{`{{- with secret`}} {{ .vaultPath | quote }} {{`}}`}}
  {{- if eq .format "env" }}
  {{`{{- range $k, $v := .Data.data }}`}}
  export {{`{{ $k }}`}}={{`"{{ $v }}"`}}
  {{`{{- end }}`}}
  {{- else if eq .format "dotenv" }}
  {{`{{- range $k, $v := .Data.data }}`}}
  {{`{{ $k }}`}}={{`{{ $v }}`}}
  {{`{{- end }}`}}
  {{- else }}
  {{`{{- .Data.data | toJSON }}`}}
  {{- end }}
  {{`{{- end }}`}}
{{- end }}
{{- end }}
{{- end }}
```

---

### `values.yaml` vault stanza — MCP Gateway

```yaml
# helm/charts/mcp-gateway/values.yaml  (extend — add vault section)
vault:
  enabled: true
  role: mcp-gateway    # matches Kubernetes auth role in TASK-US047-02
  secrets:
    # AC-3: PostgreSQL dynamic credentials — rendered to /vault/secrets/postgres
    - name:      postgres
      vaultPath: "database/postgres/creds/mcp-gateway"
      format:    env    # renders as `export USERNAME=... \n export PASSWORD=...`
    # AC-3: Redis dynamic credentials
    - name:      redis
      vaultPath: "database/redis/creds/mcp-gateway"
      format:    env
    # AC-3: Keycloak client secret (static KV)
    - name:      keycloak
      vaultPath: "secret/data/contextiq/keycloak/client"
      format:    env
```

---

### `values.yaml` vault stanza — Agent Worker

```yaml
# helm/charts/agent-worker/values.yaml  (extend)
vault:
  enabled: true
  role: agent-worker
  secrets:
    - name: postgres
      vaultPath: "database/postgres/creds/agent-worker"
      format: env
    - name: redis
      vaultPath: "database/redis/creds/agent-worker"
      format: env
    - name: neo4j
      vaultPath: "database/neo4j/creds/agent-worker"
      format: env
    - name: qdrant
      vaultPath: "secret/data/contextiq/qdrant/api-key"
      format: env
```

---

### Deployment template patch — inject Vault annotations

```yaml
# helm/charts/mcp-gateway/templates/deployment.yaml  (extend pod template metadata)
# In the pod template's metadata.annotations block, add:
    metadata:
      labels:
        {{- include "contextiq-common.selectorLabels" . | nindent 8 }}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port:   "9000"
        prometheus.io/path:   "/metrics"
        # AC-3: Vault Agent Injector annotations (rendered by helper)
        {{- include "contextiq-common.vault.annotations" . | nindent 8 }}
```

---

### Application startup: sourcing injected credentials

The Vault Agent renders credentials to `/vault/secrets/<name>` as shell-sourceable files. The container's entrypoint sources them before starting the application:

```dockerfile
# Dockerfile  (entrypoint pattern — add to existing application Dockerfiles)
ENTRYPOINT ["/bin/sh", "-c", "\
  # Source Vault-injected credentials if present \
  for f in /vault/secrets/*.env; do \
    [ -f \"$f\" ] && . \"$f\"; \
  done; \
  exec python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 \
"]
```

Alternatively, for Python services using pydantic-settings, the credentials can be passed as environment variables via a Kubernetes `envFrom` that references a `ConfigMap` generated from the Vault template (pattern preferred in EP-013 tasks). The shell-source approach is simpler and does not require a `ConfigMap` mutation step.

---

### NetworkPolicy: allow Vault Agent sidecars to reach Vault

```yaml
# k8s/network-policies/allow-rules/agents-to-vault.yaml
# Vault Agent sidecars in contextiq-agents need to reach Vault in contextiq-security
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-agents-to-vault
  namespace: contextiq-security
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: vault
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector:
            matchExpressions:
              - key: app.kubernetes.io/part-of
                operator: In
                values: [contextiq]
      ports:
        - { protocol: TCP, port: 8200 }   # Vault API
```

---

### Dev override: disable Vault injection

```yaml
# helm/charts/mcp-gateway/values-dev.yaml  (extend)
vault:
  enabled: false   # use DATABASE_URL env var directly in dev; no Vault sidecar
```

## Acceptance Criteria

- [ ] Vault Agent init-container (`vault-agent-init`) is present in running pods: `kubectl describe pod <pod> -n contextiq-gateway | grep vault-agent` (AC-3)
- [ ] `/vault/secrets/postgres.env` exists inside the mcp-gateway container and contains valid `export USERNAME=...` lines (AC-3)
- [ ] `vault list sys/leases/lookup/database/postgres/creds/mcp-gateway` shows active leases — one per running pod (AC-4)
- [ ] Sidecar (`vault-agent`) remains running alongside the app container and renews the lease before 1h TTL — verifiable by watching `vault lease lookup <lease_id>` for a `ttl` reset (AC-4)
- [ ] Deleting a pod and letting it restart generates a new, unique PostgreSQL username in `/vault/secrets/postgres.env` (AC-2, AC-4)
- [ ] `vault.enabled: false` in dev values results in no Vault annotations in rendered templates

## Dependencies

- TASK-US047-01 — Vault Agent Injector MutatingWebhookConfiguration must be registered
- TASK-US047-02 — Kubernetes auth roles must exist before pods can authenticate
- TASK-US045-02 — NetworkPolicy allow-rule for all namespaces → Vault port 8200 added to base set

## Definition of Done

- [ ] `helm template helm/charts/mcp-gateway/ | grep vault.hashicorp.com/agent-inject` returns `"true"` (when `vault.enabled: true`)
- [ ] Pod in staging starts successfully and application logs show no database connection errors
- [ ] `kubectl exec -n contextiq-gateway <pod> -- cat /vault/secrets/postgres.env` shows live credentials
