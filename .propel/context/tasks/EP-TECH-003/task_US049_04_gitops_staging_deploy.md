# TASK-US049-04 — GitOps Deploy to Staging on Merge to Main via ArgoCD

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US049-04 |
| User Story | US-049 |
| Epic | EP-TECH-003 — CI/CD Pipeline & GitOps |
| Layer | CI/CD / Infrastructure |
| Priority | P1 |
| Points | 2 |
| Status | Done |

## Description

Create the `deploy.yml` GitHub Actions workflow that triggers on every push to `main` (AC-4). It re-runs the `build` job (TASK-US049-03) for the merge commit, then updates the Helm values files in the GitOps repository with the new image SHA. ArgoCD detects the commit, syncs the staging `Application`, and waits for the rollout to complete. The entire sequence — from merge to all staging pods running the new image — must finish within 10 minutes (AC-5). Deployment to production is handled separately in TASK-US049-05.

## Implementation Details

**Technology:** GitHub Actions, ArgoCD CLI 2.11+, `argocd` Kubernetes ServiceAccount, `kubectl rollout`, Helm values update via `yq`

**File locations:**
- `.github/workflows/deploy.yml` — merge-to-main deploy workflow
- `helm/contextiq/values-staging.yaml` — staging image tag (updated by CI)
- `scripts/ci/update_image_tags.sh` — updates image tag in Helm values and commits
- `.github/argocd-staging-app.yaml` — reference to staging ArgoCD Application name

---

### Staging deploy workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to Staging

on:
  push:
    branches: [main]

# Only one deploy runs at a time; new pushes cancel in-progress deploys
concurrency:
  group: deploy-staging
  cancel-in-progress: true

env:
  ARGOCD_SERVER:    ${{ secrets.ARGOCD_SERVER }}       # e.g. argocd.contextiq.io
  ARGOCD_AUTH_TOKEN: ${{ secrets.ARGOCD_AUTH_TOKEN }}  # ArgoCD API token (repo admin)
  STAGING_APP_NAME: contextiq-staging

jobs:
  # -----------------------------------------------------------------------
  # Step 1: Build and push the merge-commit image
  # -----------------------------------------------------------------------
  build:
    name: Build Docker Images
    uses: ./.github/workflows/build.yml
    with:
      push: true
    permissions:
      contents: read
      packages: write
      id-token: write    # for SLSA attestation

  # -----------------------------------------------------------------------
  # Step 2: Update Helm values with new image SHA → commit to repo → ArgoCD picks it up
  # -----------------------------------------------------------------------
  update-image-tags:
    name: Update Staging Image Tags
    runs-on: ubuntu-24.04
    needs: build
    timeout-minutes: 3
    permissions:
      contents: write    # commit updated values file back to the repo

    steps:
      - uses: actions/checkout@v4
        with:
          # Use deploy key (not GITHUB_TOKEN) so the push triggers ArgoCD webhook
          ssh-key:       ${{ secrets.GITOPS_DEPLOY_KEY }}
          ref:           main
          fetch-depth:   1

      - name: Install yq (YAML editor)
        uses: mikefarah/yq@v4.44.3

      - name: Update image tags in Helm values
        env:
          NEW_SHA: ${{ github.sha }}
          REGISTRY: ghcr.io/${{ github.repository_owner }}
        run: |
          bash scripts/ci/update_image_tags.sh "$NEW_SHA" "$REGISTRY" \
            helm/contextiq/values-staging.yaml

      - name: Commit and push updated image tags
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add helm/contextiq/values-staging.yaml
          git diff --staged --quiet || git commit \
            -m "ci: update staging image tags to ${{ github.sha }} [skip ci]"
          git push origin main
        # [skip ci] prevents this commit from re-triggering the deploy workflow

  # -----------------------------------------------------------------------
  # Step 3: Wait for ArgoCD to sync staging Application
  # AC-4: ArgoCD sync triggered by the commit above (GitOps pull model)
  # AC-5: staging fully deployed within 10 min of merge
  # -----------------------------------------------------------------------
  wait-for-staging:
    name: Wait for Staging Deployment
    runs-on: ubuntu-24.04
    needs: update-image-tags
    timeout-minutes: 10    # AC-5: hard timeout — job fails if staging is not healthy by 10 min

    steps:
      - name: Install ArgoCD CLI
        run: |
          curl -sSL -o /usr/local/bin/argocd \
            "https://github.com/argoproj/argo-cd/releases/download/v2.11.5/argocd-linux-amd64"
          chmod +x /usr/local/bin/argocd

      # AC-4: wait for ArgoCD to detect the GitOps commit and start syncing
      # The polling below checks sync status every 15s for up to 8 min
      - name: Wait for ArgoCD sync to start
        env:
          ARGOCD_OPTS: "--server ${{ env.ARGOCD_SERVER }} --auth-token ${{ env.ARGOCD_AUTH_TOKEN }} --grpc-web"
        run: |
          echo "Waiting for ArgoCD to pick up the new commit..."
          DEADLINE=$(( $(date +%s) + 480 ))    # 8 min deadline
          while [ $(date +%s) -lt $DEADLINE ]; do
            SYNC_STATUS=$(argocd app get "${{ env.STAGING_APP_NAME }}" \
              --output json 2>/dev/null | jq -r '.status.sync.status' || echo "Unknown")
            HEALTH=$(argocd app get "${{ env.STAGING_APP_NAME }}" \
              --output json 2>/dev/null | jq -r '.status.health.status' || echo "Unknown")
            echo "  SyncStatus=$SYNC_STATUS  Health=$HEALTH"
            if [ "$SYNC_STATUS" = "Synced" ] && [ "$HEALTH" = "Healthy" ]; then
              echo "SUCCESS: Staging is Synced and Healthy"
              break
            fi
            sleep 15
          done

          # Final status check
          argocd app get "${{ env.STAGING_APP_NAME }}" \
            --output json | jq '{sync: .status.sync.status, health: .status.health.status}'

      # Confirm that the running pods carry the expected image SHA
      - name: Verify image SHA on deployed pods
        run: |
          EXPECTED_SHA="${{ github.sha }}"
          NAMESPACES=(contextiq-gateway contextiq-agents contextiq-admin)
          for NS in "${NAMESPACES[@]}"; do
            RUNNING_SHA=$(kubectl get pods -n "$NS" \
              -o jsonpath='{.items[0].spec.containers[0].image}' 2>/dev/null \
              | awk -F: '{print $2}')
            echo "  $NS: deployed SHA = $RUNNING_SHA (expected: $EXPECTED_SHA)"
            if [ "$RUNNING_SHA" != "$EXPECTED_SHA" ]; then
              echo "FAIL: $NS pods still running old image"
              exit 1
            fi
          done
          echo "PASS: All namespaces running expected SHA $EXPECTED_SHA"

      # Post deployment timing summary as a PR / commit comment
      - name: Post deployment summary
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const start = new Date('${{ github.event.head_commit.timestamp }}');
            const elapsed = Math.round((Date.now() - start.getTime()) / 1000);
            github.rest.repos.createCommitComment({
              owner: context.repo.owner,
              repo:  context.repo.repo,
              commit_sha: context.sha,
              body: `**Staging Deployment** — \`${{ env.STAGING_APP_NAME }}\`\n`
                  + `SHA: \`${{ github.sha }}\`\n`
                  + `Elapsed: **${elapsed}s** (target: < 600s)\n`
                  + (elapsed < 600 ? '✅ Within 10-minute budget' : '⚠️ Exceeded 10-minute budget'),
            });
```

---

### Image tag update script

```bash
#!/usr/bin/env bash
# scripts/ci/update_image_tags.sh
# Updates the imageTag fields in a Helm values file to the new git SHA.
#
# Usage: update_image_tags.sh <git-sha> <registry> <values-file>
set -euo pipefail

NEW_SHA="$1"
REGISTRY="$2"
VALUES_FILE="$3"

echo "=== Updating image tags in $VALUES_FILE to $NEW_SHA ==="

# Services that have independent image tags in the values file
SERVICES=(mcp-gateway agent-worker indexing-service admin-api)

for SVC in "${SERVICES[@]}"; do
  yq e ".${SVC//-/_}.image.tag = \"$NEW_SHA\"" -i "$VALUES_FILE"
  echo "  Updated ${SVC} → ${NEW_SHA}"
done

echo "=== Image tag update complete ==="
cat "$VALUES_FILE"
```

---

### Staging Helm values structure

```yaml
# helm/contextiq/values-staging.yaml  (managed by CI — do not edit manually)
# Image tags are updated by scripts/ci/update_image_tags.sh on every main-branch merge.
mcp_gateway:
  image:
    repository: ghcr.io/org/contextiq-api
    tag: "PLACEHOLDER"    # replaced by CI with git SHA

agent_worker:
  image:
    repository: ghcr.io/org/contextiq-agent-worker
    tag: "PLACEHOLDER"

indexing_service:
  image:
    repository: ghcr.io/org/contextiq-indexing
    tag: "PLACEHOLDER"

admin_api:
  image:
    repository: ghcr.io/org/contextiq-api
    tag: "PLACEHOLDER"
```

---

### ArgoCD Application: `contextiq-staging`

```yaml
# argocd/apps/envs/contextiq-staging.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: contextiq-staging
  namespace: argocd
spec:
  project: contextiq
  source:
    repoURL:        https://github.com/org/contextiq.git
    targetRevision: main    # always track main branch — CI commits updated image tags here
    path:           helm/contextiq
    helm:
      valueFiles:
        - values.yaml
        - values-staging.yaml    # contains the CI-updated image tags
  destination:
    server:    https://kubernetes.default.svc
    namespace: contextiq-gateway    # umbrella chart deploys across namespaces
  syncPolicy:
    automated:
      prune:     true
      selfHeal:  true
    syncOptions:
      - CreateNamespace=false
      - ApplyOutOfSyncOnly=true    # only sync changed resources — reduces sync time (AC-7)
    retry:
      limit: 3
      backoff:
        duration:    5s
        maxDuration: 3m
        factor:      2
```

## Acceptance Criteria

- [x] A merge to `main` triggers the `Deploy to Staging` workflow within 30 seconds of the merge (AC-4)
- [x] `values-staging.yaml` in the repository is updated with the new git SHA within 2 minutes of merge (AC-4)
- [x] `argocd app get contextiq-staging` shows `SyncStatus=Synced` and `Health=Healthy` after the workflow completes (AC-4)
- [x] Workflow `wait-for-staging` job completes within 10 minutes of the merge commit timestamp (AC-5)
- [x] Running pods in `contextiq-gateway` carry the correct SHA tag — verified by the `Verify image SHA` step (AC-5)
- [x] Deployment timing posted as a commit comment — elapsed time visible without accessing workflow logs (AC-5)

## Dependencies

- TASK-US049-01 — `pr-checks.yml` workflow structure for pattern reference
- TASK-US049-03 — `build.yml` reusable workflow must exist
- TASK-US045-04 — ArgoCD `contextiq-staging` Application must exist before this workflow triggers sync
- `ARGOCD_SERVER` and `ARGOCD_AUTH_TOKEN` must be added as GitHub Actions secrets by a repo admin
- `GITOPS_DEPLOY_KEY` — SSH deploy key with write access to the repo (so the image-tag commit triggers ArgoCD webhook)
- `yq` v4 available in the CI runner (installed inline by the workflow step)

## Definition of Done

- [x] `.github/workflows/deploy.yml` merged to `main`
- [x] `scripts/ci/update_image_tags.sh` committed and executable (`chmod +x`)
- [x] First deploy after merge completes within 10 minutes; commit comment shows elapsed < 600s
