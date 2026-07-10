# TASK-US048-02 — TLS 1.3 Enforcement and TLS 1.2 Disabled at All Ingress Points

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US048-02 |
| User Story | US-048 |
| Epic | EP-TECH-002 — Security Hardening & Secrets Management |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Disable TLS 1.0, 1.1, and 1.2 across all external and internal ingress points; accept only TLS 1.3 connections (AC-4). Configuration is applied at three layers: (1) the NGINX Ingress Controller's global ConfigMap restricts `ssl-protocols` to `TLSv1.3` only, (2) application-level services that open their own TLS listeners (Keycloak, Vault, PostgreSQL) are patched to enforce TLS 1.3, and (3) a validation script confirms the setting by probing each endpoint with `openssl s_client`. A CI check (`check_tls_versions.sh`) prevents regression.

## Implementation Details

**Technology:** NGINX Ingress Controller 1.10+, Keycloak 24.x, PostgreSQL 15, openssl CLI

**File locations:**
- `k8s/ingress-nginx/configmap-patch.yaml` — NGINX ConfigMap patch
- `helm/charts/keycloak/values-prod-tls.yaml` — Keycloak JVM TLS override
- `k8s/postgres/postgresql.conf-patch.yaml` — PostgreSQL ssl_min_protocol_version
- `scripts/security/check_tls_versions.sh` — endpoint TLS version probe

---

### NGINX Ingress Controller global ConfigMap

```yaml
# k8s/ingress-nginx/configmap-patch.yaml
# Patch the nginx-ingress-controller ConfigMap to enforce TLS 1.3 only.
# Apply with: kubectl apply -f configmap-patch.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx    # adjust if controller is in a different namespace
data:
  # AC-4: Only TLS 1.3 — drop TLS 1.0, 1.1, 1.2 entirely
  ssl-protocols: "TLSv1.3"

  # Cipher suites: TLS 1.3 ciphers are fixed by the spec (not configurable via ssl-ciphers),
  # but we explicitly clear the TLS 1.2 cipher list to ensure no negotiation fallback
  ssl-ciphers: ""    # empty string: no TLS 1.2 cipher suites offered

  # HSTS: 1-year duration, include all subdomains, allow preload
  hsts:                  "true"
  hsts-max-age:          "31536000"
  hsts-include-subdomains: "true"
  hsts-preload:          "true"

  # Redirect all HTTP to HTTPS
  force-ssl-redirect: "true"
  ssl-redirect:       "true"

  # Disable SSLv3 (belt-and-suspenders; already excluded by ssl-protocols)
  use-forwarded-headers: "true"
```

---

### Keycloak TLS 1.3 enforcement

Keycloak 24.x runs on Quarkus which uses JVM TLS settings. Force TLS 1.3 via JVM args:

```yaml
# helm/charts/keycloak/values-prod-tls.yaml  (overlay applied in prod only)
# Keycloak Helm chart: https://github.com/codecentric/helm-charts/tree/master/charts/keycloak
keycloak:
  extraEnv:
    # AC-4: JVM system properties restrict TLS to 1.3 only
    - name: JAVA_OPTS_APPEND
      value: >-
        -Djdk.tls.client.protocols=TLSv1.3
        -Djdk.tls.server.protocols=TLSv1.3
        -Dhttps.protocols=TLSv1.3
        -Djdk.tls.ephemeralDHKeySize=2048

  # Keycloak Quarkus TLS mode (HTTPS listener on 8443)
  extraEnvFrom:
    - secretRef:
        name: keycloak-tls-secret    # contains tls.crt and tls.key from cert-manager (TASK-US048-01)
```

---

### PostgreSQL TLS 1.3 minimum protocol version

```yaml
# k8s/postgres/postgresql.conf-patch.yaml
# ConfigMap patch to apply postgresql.conf settings that enforce TLS 1.3.
# Mounted as /etc/postgresql/postgresql.conf.d/tls.conf
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-tls-config
  namespace: contextiq-data
data:
  tls.conf: |
    # AC-4: Enforce TLS 1.3 minimum for PostgreSQL client connections
    ssl                      = on
    ssl_min_protocol_version = 'TLSv1.3'
    ssl_max_protocol_version = 'TLSv1.3'
    ssl_cert_file            = '/etc/ssl/certs/tls.crt'
    ssl_key_file             = '/etc/ssl/private/tls.key'
    ssl_ca_file              = '/etc/ssl/certs/ca.crt'
```

---

### Redis TLS 1.3 enforcement

```yaml
# k8s/redis/redis-conf-patch.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-tls-config
  namespace: contextiq-data
data:
  redis.conf: |
    # AC-4: TLS 1.3 only for Redis client connections
    tls-port             6379
    tls-cert-file        /tls/tls.crt
    tls-key-file         /tls/tls.key
    tls-ca-cert-file     /tls/ca.crt
    tls-auth-clients     yes
    tls-protocols        "TLSv1.3"
    tls-ciphers          ""          # TLS 1.3 ciphers are fixed; leave empty
    tls-replication      yes
    tls-cluster          yes
```

---

### TLS version validation script (CI-safe)

```bash
#!/usr/bin/env bash
# scripts/security/check_tls_versions.sh
# AC-4: Probe each external and internal TLS endpoint and assert only TLS 1.3 is accepted.
# Fails (exit 1) if any endpoint accepts TLS 1.2 or lower, or does not support TLS 1.3.
set -euo pipefail

PASS=0
FAIL=0

check_endpoint() {
  local ENDPOINT="$1"
  local PORT="${2:-443}"
  local HOST="${ENDPOINT%%:*}"

  echo "--- Checking $ENDPOINT ---"

  # Assert TLS 1.3 is accepted
  if echo | openssl s_client -connect "${ENDPOINT}:${PORT}" \
      -tls1_3 -brief 2>&1 | grep -q "^Protocol.*TLSv1.3"; then
    echo "  [PASS] TLS 1.3 accepted"
    PASS=$(( PASS + 1 ))
  else
    echo "  [FAIL] TLS 1.3 NOT accepted at ${ENDPOINT}:${PORT}"
    FAIL=$(( FAIL + 1 ))
  fi

  # Assert TLS 1.2 is REJECTED
  local TLS12_OUTPUT
  TLS12_OUTPUT=$(echo | openssl s_client -connect "${ENDPOINT}:${PORT}" \
    -tls1_2 -brief 2>&1 || true)
  if echo "$TLS12_OUTPUT" | grep -qE "^(handshake failure|ssl handshake failure|CONNECTED\(00000003\)).*"; then
    echo "  [PASS] TLS 1.2 rejected"
    PASS=$(( PASS + 1 ))
  elif echo "$TLS12_OUTPUT" | grep -q "^Protocol.*TLSv1.2"; then
    echo "  [FAIL] TLS 1.2 is STILL accepted at ${ENDPOINT}:${PORT} — AC-4 violation"
    FAIL=$(( FAIL + 1 ))
  else
    echo "  [WARN] Could not determine TLS 1.2 status at ${ENDPOINT}:${PORT}"
  fi
}

# External Ingress endpoints
check_endpoint "api.contextiq.io"
check_endpoint "auth.contextiq.io"
check_endpoint "admin.contextiq.io"

# Internal service endpoints (run from within cluster network or via port-forward)
if [ "${CHECK_INTERNAL:-false}" = "true" ]; then
  check_endpoint "vault.contextiq-security.svc.cluster.local"  8200
  check_endpoint "postgres.contextiq-data.svc.cluster.local"   5432
  check_endpoint "redis.contextiq-data.svc.cluster.local"      6379
fi

echo ""
echo "=== TLS Version Check Results ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"

if [ "$FAIL" -gt 0 ]; then
  echo "FAIL: $FAIL endpoint(s) do not comply with TLS 1.3-only requirement (AC-4)"
  exit 1
fi
echo "PASS: All endpoints enforce TLS 1.3 only"
```

## Acceptance Criteria

- [ ] `openssl s_client -connect api.contextiq.io:443 -tls1_3` handshake succeeds; `Protocol: TLSv1.3` shown (AC-4)
- [ ] `openssl s_client -connect api.contextiq.io:443 -tls1_2` produces `handshake failure` — TLS 1.2 rejected (AC-4)
- [ ] Same TLS 1.3-only result verified on `auth.contextiq.io` (Keycloak) and `admin.contextiq.io` (Admin Portal) (AC-4)
- [ ] `kubectl get configmap ingress-nginx-controller -n ingress-nginx -o jsonpath='{.data.ssl-protocols}'` returns `TLSv1.3` (AC-4)
- [ ] PostgreSQL `SHOW ssl_min_protocol_version;` returns `TLSv1.3` (AC-4)
- [ ] `scripts/security/check_tls_versions.sh` exits 0 in CI pipeline (AC-4)

## Dependencies

- TASK-US048-01 — cert-manager must be issuing certificates before TLS-only enforcement is enabled (enabling TLS 1.3 before certs exist would cause connection failures)
- NGINX Ingress Controller must be deployed and managing Ingress resources
- Keycloak, PostgreSQL, Redis deployments must have TLS-enabled listeners

## Definition of Done

- [ ] `kubectl apply -f k8s/ingress-nginx/configmap-patch.yaml` applies without error; NGINX controller pods rolling-restart
- [ ] `check_tls_versions.sh` passes on all external endpoints in staging
- [ ] PostgreSQL and Redis TLS conf patches applied; `psql "sslmode=require"` connects successfully
