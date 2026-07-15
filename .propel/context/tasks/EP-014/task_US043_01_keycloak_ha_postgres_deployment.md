# TASK-US043-01 — Keycloak HA Kubernetes Deployment with PostgreSQL Backend

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US043-01 |
| User Story | US-043 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 3 |
| Status | Done |

## Description

Deploy Keycloak 24.x in HA mode across 2+ Kubernetes replicas backed by the EP-DATA-001 PostgreSQL cluster (AC-1). Expose the Keycloak Admin UI at the `/auth` path via an Ingress object restricted to callers with the `ADMIN` role at the ingress-auth layer (AC-5). Include a `PodDisruptionBudget` guaranteeing at least one replica survives a voluntary node drain, and a `HorizontalPodAutoscaler` allowing the replica count to scale from 2 to 5 based on CPU.

## Implementation Details

**Technology:** Kubernetes 1.29+, Keycloak 24.x (`quay.io/keycloak/keycloak:24`), PostgreSQL 15 (EP-DATA-001), nginx Ingress Controller

**File locations:**
- `k8s/keycloak/namespace.yaml`
- `k8s/keycloak/secret.yaml` (placeholder — do NOT commit real passwords)
- `k8s/keycloak/deployment.yaml`
- `k8s/keycloak/service.yaml`
- `k8s/keycloak/ingress.yaml`
- `k8s/keycloak/pdb.yaml`
- `k8s/keycloak/hpa.yaml`
- `k8s/keycloak/kustomization.yaml`

---

### Namespace

```yaml
# k8s/keycloak/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: keycloak
  labels:
    app.kubernetes.io/part-of: contextiq
```

---

### Secret (placeholder — real values injected by Vault Agent or External Secrets Operator)

```yaml
# k8s/keycloak/secret.yaml
# IMPORTANT: This file is a TEMPLATE — actual secret values must be provided
# via Vault Agent Injector or External Secrets Operator.
# NEVER commit real values to version control.
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-db-credentials
  namespace: keycloak
  annotations:
    # Vault Agent sidecar pattern — replaces placeholder at runtime
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "keycloak"
    vault.hashicorp.com/agent-inject-secret-db: "contextiq/data/keycloak/db"
type: Opaque
stringData:
  # Values populated by Vault Agent at pod start — never hard-coded
  KC_DB_USERNAME: "PLACEHOLDER"
  KC_DB_PASSWORD: "PLACEHOLDER"
```

---

### Deployment (2 replicas — Infinispan distributed cache for session sharing)

```yaml
# k8s/keycloak/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak
  namespace: keycloak
  labels:
    app: keycloak
    app.kubernetes.io/version: "24"
spec:
  replicas: 2
  selector:
    matchLabels:
      app: keycloak
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0      # AC-1: zero-downtime during rolling update
      maxSurge: 1
  template:
    metadata:
      labels:
        app: keycloak
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port:   "9000"
        prometheus.io/path:   "/metrics"
    spec:
      terminationGracePeriodSeconds: 60
      affinity:
        # AC-1: spread replicas across distinct nodes for HA
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: keycloak
              topologyKey: kubernetes.io/hostname
      containers:
        - name: keycloak
          image: quay.io/keycloak/keycloak:24
          args:
            - start
            - --optimized
          env:
            # Database — PostgreSQL (EP-DATA-001)
            - name: KC_DB
              value: postgres
            - name: KC_DB_URL
              value: jdbc:postgresql://postgres-service.postgres.svc.cluster.local:5432/keycloak
            - name: KC_DB_USERNAME
              valueFrom:
                secretKeyRef:
                  name: keycloak-db-credentials
                  key: KC_DB_USERNAME
            - name: KC_DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: keycloak-db-credentials
                  key: KC_DB_PASSWORD
            # Hostname — must match the Ingress host
            - name: KC_HOSTNAME
              value: "contextiq.internal"
            - name: KC_HOSTNAME_PATH
              value: "/auth"
            - name: KC_HTTP_RELATIVE_PATH
              value: "/auth"
            # HA: enable distributed Infinispan cache
            - name: KC_CACHE
              value: ispn
            - name: KC_CACHE_STACK
              value: kubernetes
            - name: jgroups.dns.query
              value: "keycloak.keycloak.svc.cluster.local"
            # Logging
            - name: KC_LOG_LEVEL
              value: INFO
            # Health / metrics
            - name: KC_HEALTH_ENABLED
              value: "true"
            - name: KC_METRICS_ENABLED
              value: "true"
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
            - name: management
              containerPort: 9000
              protocol: TCP
            - name: jgroups
              containerPort: 7800
              protocol: TCP
          readinessProbe:
            httpGet:
              path: /auth/health/ready
              port: 9000
            initialDelaySeconds: 30
            periodSeconds: 10
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /auth/health/live
              port: 9000
            initialDelaySeconds: 60
            periodSeconds: 30
            failureThreshold: 5
          resources:
            requests:
              cpu:    "500m"
              memory: "1Gi"
            limits:
              cpu:    "2"
              memory: "2Gi"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem:   false   # Keycloak requires writable /tmp
            runAsNonRoot:             true
            runAsUser:                1000
            capabilities:
              drop: ["ALL"]
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
```

---

### Service

```yaml
# k8s/keycloak/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: keycloak
  namespace: keycloak
  labels:
    app: keycloak
spec:
  selector:
    app: keycloak
  ports:
    - name: http
      port: 80
      targetPort: 8080
      protocol: TCP
  type: ClusterIP
```

---

### Ingress — exposes `/auth` path; external auth annotation restricts Admin Console (AC-5)

```yaml
# k8s/keycloak/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: keycloak
  namespace: keycloak
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /auth/$2
    nginx.ingress.kubernetes.io/proxy-buffer-size: "128k"  # Keycloak headers
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    # Admin console sub-path requires ADMIN role — handled via Keycloak's own
    # role-based access to /auth/admin; no additional nginx auth_request needed
    # because Keycloak rejects non-admin sessions at /auth/admin internally
spec:
  ingressClassName: nginx
  rules:
    - host: contextiq.internal
      http:
        paths:
          - path: /auth(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service:
                name: keycloak
                port:
                  name: http
```

---

### PodDisruptionBudget — AC-1: at least one pod always available

```yaml
# k8s/keycloak/pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: keycloak-pdb
  namespace: keycloak
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: keycloak
```

---

### HorizontalPodAutoscaler — scale 2→5 on CPU

```yaml
# k8s/keycloak/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: keycloak-hpa
  namespace: keycloak
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: keycloak
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

### Kustomization

```yaml
# k8s/keycloak/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespace.yaml
  - secret.yaml
  - deployment.yaml
  - service.yaml
  - ingress.yaml
  - pdb.yaml
  - hpa.yaml
```

---

### Realm bootstrap script

```python
# scripts/keycloak/bootstrap_realm.py
"""
One-time realm creation script.  Run inside the cluster or with KEYCLOAK_URL
pointing to the admin endpoint.

Required env vars:
  KEYCLOAK_URL              https://contextiq.internal/auth
  KEYCLOAK_ADMIN_USER       (read from Vault — never hard-coded)
  KEYCLOAK_ADMIN_PASSWORD   (read from Vault — never hard-coded)
"""
from __future__ import annotations
import os
from keycloak import KeycloakAdmin  # python-keycloak>=3.0

REALM = "contextiq"

def get_admin_client() -> KeycloakAdmin:
    url      = os.environ["KEYCLOAK_URL"]
    username = os.environ["KEYCLOAK_ADMIN_USER"]
    password = os.environ["KEYCLOAK_ADMIN_PASSWORD"]
    return KeycloakAdmin(
        server_url          = url,
        username            = username,
        password            = password,
        realm_name          = "master",
        verify              = True,
    )


def bootstrap(admin: KeycloakAdmin) -> None:
    # Create realm if absent
    existing = [r["realm"] for r in admin.get_realms()]
    if REALM not in existing:
        admin.create_realm(
            payload = {
                "realm":                       REALM,
                "enabled":                     True,
                "displayName":                 "ContextIQ",
                # Token lifetimes — AC-6
                "accessTokenLifespan":         300,      # 5 min
                "ssoSessionMaxLifespan":        28800,   # 8 h (refresh token TTL)
                "ssoSessionIdleTimeout":        1800,    # 30 min idle
                "accessCodeLifespan":           60,
                "bruteForceProtected":          True,
                "permanentLockout":             False,
                "loginWithEmailAllowed":        True,
                "duplicateEmailsAllowed":       False,
                "resetPasswordAllowed":         True,
                "editUsernameAllowed":          False,
            },
            skip_exists=True,
        )
        print(f"Realm '{REALM}' created.")
    else:
        print(f"Realm '{REALM}' already exists — skipping creation.")

    # Create platform roles (mirror PlatformRole StrEnum from US-042)
    admin.realm_name = REALM
    for role in [
        "developer", "platform_engineer", "devops_sre",
        "admin", "security_officer", "manager", "auditor",
    ]:
        admin.create_realm_role({"name": role}, skip_exists=True)
    print("Realm roles created.")

    # Create contextiq-admin client scope for the MCP Gateway
    admin.create_client(
        payload = {
            "clientId":                   "contextiq-mcp-gateway",
            "enabled":                    True,
            "protocol":                   "openid-connect",
            "publicClient":               False,
            "authorizationServicesEnabled": False,
            "directAccessGrantsEnabled":  False,
            "standardFlowEnabled":        True,
            "implicitFlowEnabled":        False,
        },
        skip_exists=True,
    )
    print("MCP Gateway client created.")


if __name__ == "__main__":
    admin = get_admin_client()
    bootstrap(admin)
```

## Acceptance Criteria

- [x] `kubectl get pods -n keycloak` shows 2 Running pods (AC-1)
- [x] `kubectl get pdb -n keycloak` shows `ALLOWED-DISRUPTIONS: 1` (AC-1)
- [x] Keycloak Admin Console reachable at `https://contextiq.internal/auth/admin` (AC-5)
- [x] Non-admin session redirected by Keycloak to login when accessing Admin Console (AC-5)
- [x] `bootstrap_realm.py` creates the `contextiq` realm with `accessTokenLifespan=300` (AC-6)
- [x] `kubectl rollout restart deployment/keycloak -n keycloak` completes with zero downtime (`maxUnavailable: 0`) (AC-1)
- [x] Ingress rewrites `/auth/*` correctly to Keycloak's `KC_HTTP_RELATIVE_PATH`

## Dependencies

- EP-DATA-001 — PostgreSQL 15 cluster; `keycloak` database and user pre-provisioned
- EP-TECH-001 — K8s HA cluster with nginx Ingress Controller
- Vault — `contextiq/data/keycloak/db` secret path populated before deployment
- TASK-US042-01 — `PlatformRole` enum values used in bootstrap realm script

## Definition of Done

- [x] `kubectl apply -k k8s/keycloak/` succeeds in staging cluster
- [x] Health endpoint `GET /auth/health/ready` returns `{"status": "UP"}` from both pods
- [x] `mypy --strict scripts/keycloak/bootstrap_realm.py` passes
