# TASK-US045-04 — ArgoCD App-of-Apps: Git-Synced Helm Releases

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US045-04 |
| User Story | US-045 |
| Epic | EP-TECH-001 — Platform Infrastructure & Kubernetes |
| Layer | Infrastructure |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Configure ArgoCD using the App-of-Apps pattern (AC-7): a root `Application` object points at a directory of per-service `Application` manifests in the Git repository. ArgoCD watches the repo and automatically syncs any drift between the Git-declared state and the live cluster state. Each service `Application` references a Helm chart from TASK-US045-03 and specifies the correct environment `values` file. The ArgoCD project (`contextiq`) defines RBAC and source/destination constraints so only approved repos and namespaces can be targeted.

## Implementation Details

**Technology:** ArgoCD 2.11+, Helm 3.15+, Kubernetes 1.29+

**File locations:**
- `argocd/projects/contextiq-project.yaml` — ArgoCD `AppProject`
- `argocd/apps/root-app.yaml` — root App-of-Apps `Application`
- `argocd/apps/services/` — one `Application` manifest per service
- `argocd/apps/services/mcp-gateway.yaml`
- `argocd/apps/services/agent-worker.yaml`
- `argocd/apps/services/admin-portal.yaml`
- `argocd/apps/services/keycloak.yaml`
- `argocd/apps/services/jaeger.yaml`
- `argocd/apps/services/opa.yaml`
- `argocd/apps/kustomization.yaml`

---

### ArgoCD `AppProject` — source and destination constraints

```yaml
# argocd/projects/contextiq-project.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: contextiq
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: "ContextIQ platform services"

  # Only allow deployments from the canonical Git repository
  sourceRepos:
    - "https://github.com/your-org/contextiq.git"

  # Only allow deployments to the 7 ContextIQ namespaces
  destinations:
    - namespace: contextiq-gateway
      server: https://kubernetes.default.svc
    - namespace: contextiq-agents
      server: https://kubernetes.default.svc
    - namespace: contextiq-data
      server: https://kubernetes.default.svc
    - namespace: contextiq-admin
      server: https://kubernetes.default.svc
    - namespace: contextiq-observability
      server: https://kubernetes.default.svc
    - namespace: contextiq-security
      server: https://kubernetes.default.svc
    - namespace: contextiq-infra
      server: https://kubernetes.default.svc
    # ArgoCD itself deploys Application objects to the argocd namespace
    - namespace: argocd
      server: https://kubernetes.default.svc

  # Restrict manageable Kubernetes resources — deny ClusterRole/ClusterRoleBinding
  # from application-level charts (platform team manages those separately)
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace    # umbrella chart may create namespace labels

  namespaceResourceBlacklist:
    - group: "rbac.authorization.k8s.io"
      kind: ClusterRole
    - group: "rbac.authorization.k8s.io"
      kind: ClusterRoleBinding

  # ArgoCD RBAC: Platform Engineers can sync; read-only for all others
  roles:
    - name: platform-engineer
      policies:
        - "p, proj:contextiq:platform-engineer, applications, sync, contextiq/*, allow"
        - "p, proj:contextiq:platform-engineer, applications, get,  contextiq/*, allow"
      groups:
        - contextiq-platform-engineers    # Keycloak group name (via ArgoCD SSO)
    - name: read-only
      policies:
        - "p, proj:contextiq:read-only, applications, get, contextiq/*, allow"
      groups:
        - contextiq-developers
        - contextiq-auditors
```

---

### Root App-of-Apps `Application`

```yaml
# argocd/apps/root-app.yaml
# AC-7: The root application points to the argocd/apps/services/ directory.
# ArgoCD recursively discovers and syncs every Application manifest it contains.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: contextiq-apps
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           argocd/apps/services
  destination:
    server:    https://kubernetes.default.svc
    namespace: argocd    # Application objects live in argocd namespace
  syncPolicy:
    automated:
      prune:    true     # remove resources deleted from Git
      selfHeal: true     # revert manual cluster changes
    syncOptions:
      - CreateNamespace=false   # namespaces managed by TASK-US045-01
      - PrunePropagationPolicy=foreground
      - ApplyOutOfSyncOnly=true
```

---

### Per-service `Application` manifests

```yaml
# argocd/apps/services/mcp-gateway.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mcp-gateway
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/mcp-gateway
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml   # environment-specific overrides (AC-2)
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-gateway
  syncPolicy:
    automated:
      prune:    true
      selfHeal: true
    syncOptions:
      - ApplyOutOfSyncOnly=true
  # AC-6: ArgoCD waits for all pods to be healthy before marking the sync complete
  ignoreDifferences:
    - group: apps
      kind:  Deployment
      jsonPointers:
        - /spec/replicas   # ignore HPA-driven replica count drift
---
# argocd/apps/services/agent-worker.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: agent-worker
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/agent-worker
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-agents
  syncPolicy:
    automated: { prune: true, selfHeal: true }
---
# argocd/apps/services/admin-portal.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: admin-portal
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/admin-portal
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-admin
  syncPolicy:
    automated: { prune: true, selfHeal: true }
---
# argocd/apps/services/keycloak.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: keycloak
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/keycloak
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-security
  syncPolicy:
    automated: { prune: true, selfHeal: true }
---
# argocd/apps/services/jaeger.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: jaeger
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/jaeger
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-observability
  syncPolicy:
    automated: { prune: true, selfHeal: true }
---
# argocd/apps/services/opa.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: opa
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/your-org/contextiq.git
    targetRevision: HEAD
    path:           helm/charts/opa
    helm:
      valueFiles: [values.yaml, values-prod.yaml]
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-security
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

---

### ArgoCD SSO integration with Keycloak

```yaml
# argocd/argocd-cm-patch.yaml  (applied via Kustomize patch to the argocd ConfigMap)
# Configures ArgoCD to authenticate users via the Keycloak contextiq realm (OIDC).
data:
  url: https://argocd.contextiq.internal
  oidc.config: |
    name: Keycloak
    issuer: https://contextiq.internal/auth/realms/contextiq
    clientID: argocd
    clientSecret: $oidc.keycloak.clientSecret   # references argocd-secret
    requestedScopes: ["openid", "profile", "email", "groups"]
    groupsClaim: groups
```

---

### Kustomization for ArgoCD manifests

```yaml
# argocd/apps/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../projects/contextiq-project.yaml
  - root-app.yaml
  - services/mcp-gateway.yaml
  - services/agent-worker.yaml
  - services/admin-portal.yaml
  - services/keycloak.yaml
  - services/jaeger.yaml
  - services/opa.yaml
```

## Acceptance Criteria

- [ ] `kubectl get applications -n argocd` shows one `Application` per service, all with `Sync Status: Synced` (AC-7)
- [ ] Pushing a change to `helm/charts/mcp-gateway/values-prod.yaml` in Git triggers an automatic ArgoCD sync within 3 minutes (AC-7)
- [ ] Manual `kubectl scale deployment/mcp-gateway --replicas=1` is reverted by ArgoCD `selfHeal: true` within the next sync cycle (AC-7)
- [ ] `argocd app get contextiq-apps` shows `Health Status: Healthy` (AC-7)
- [ ] ArgoCD denies a sync targeting a namespace not in the `AppProject.destinations` list (project RBAC) (AC-7)
- [ ] `ignoreDifferences` for `/spec/replicas` prevents HPA-driven replica counts from being marked Out-of-Sync

## Dependencies

- TASK-US045-01 — namespaces must exist (`CreateNamespace=false` in sync options)
- TASK-US045-03 — Helm charts must exist at the referenced `path` in Git
- ArgoCD 2.11+ installed in cluster (typically bootstrapped via Helm before this task)

## Definition of Done

- [ ] `kubectl apply -k argocd/apps/` succeeds
- [ ] All service `Application` objects reach `Synced / Healthy` in ArgoCD UI
- [ ] ArgoCD SSO login via Keycloak works for users with `platform_engineer` role
