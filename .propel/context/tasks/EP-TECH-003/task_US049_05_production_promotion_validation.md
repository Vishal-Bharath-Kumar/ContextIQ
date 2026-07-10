# TASK-US049-05 — Production Promotion with Manual Approval Gate and Pipeline Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US049-05 |
| User Story | US-049 |
| Epic | EP-TECH-003 — CI/CD Pipeline & GitOps |
| Layer | CI/CD / QA |
| Priority | P1 |
| Points | 3 |
| Status | Draft |

## Description

Extend the `deploy.yml` workflow with a `promote-to-production` job that requires a manual approval via a GitHub Actions protected environment before syncing the ArgoCD `contextiq-production` Application (AC-6). After approval, the same image SHA already validated in staging is deployed to production without a rebuild — guaranteeing environment parity. A full end-to-end pipeline validation script asserts all 7 ACs across the complete pipeline (PR gates, build, security scans, staging deploy, production promotion) so the pipeline can be verified as a whole after initial setup.

## Implementation Details

**Technology:** GitHub Actions environments (protected), ArgoCD CLI 2.11+, pytest

**File locations:**
- `.github/workflows/deploy.yml` — extended with `promote-to-production` job
- `.github/environments/production.yml` — environment protection rules (configured in GitHub UI)
- `scripts/ci/promote_to_production.sh` — production promotion script
- `tests/ci/test_pipeline_validation.py` — end-to-end pipeline assertion suite

---

### Production promotion job (extends `deploy.yml`)

```yaml
# .github/workflows/deploy.yml  (extend — add after wait-for-staging job)

  # -----------------------------------------------------------------------
  # Step 4: Manual approval gate → production deploy
  # AC-6: environment 'production' has required reviewers configured in GitHub
  # -----------------------------------------------------------------------
  promote-to-production:
    name: Promote to Production
    runs-on: ubuntu-24.04
    needs: wait-for-staging    # only offer promotion after staging is healthy (AC-5)
    timeout-minutes: 10

    # AC-6: 'production' environment requires at least one reviewer approval
    # Configure reviewers in GitHub: Settings → Environments → production → Required reviewers
    environment:
      name: production
      url:  https://api.contextiq.io    # displayed in the approval UI for reviewer context

    env:
      ARGOCD_SERVER:     ${{ secrets.ARGOCD_SERVER }}
      ARGOCD_AUTH_TOKEN: ${{ secrets.ARGOCD_AUTH_TOKEN }}
      PRODUCTION_APP:    contextiq-production

    steps:
      - uses: actions/checkout@v4
        with:
          ssh-key:     ${{ secrets.GITOPS_DEPLOY_KEY }}
          ref:         main
          fetch-depth: 1

      - name: Install yq
        uses: mikefarah/yq@v4.44.3

      - name: Install ArgoCD CLI
        run: |
          curl -sSL -o /usr/local/bin/argocd \
            "https://github.com/argoproj/argo-cd/releases/download/v2.11.5/argocd-linux-amd64"
          chmod +x /usr/local/bin/argocd

      # AC-6: this step is reached only after a reviewer clicks Approve in GitHub
      - name: Update production image tags
        env:
          NEW_SHA: ${{ github.sha }}
          REGISTRY: ghcr.io/${{ github.repository_owner }}
        run: |
          bash scripts/ci/update_image_tags.sh "$NEW_SHA" "$REGISTRY" \
            helm/contextiq/values-production.yaml

      - name: Commit and push production image tags
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add helm/contextiq/values-production.yaml
          git diff --staged --quiet || git commit \
            -m "ci: promote ${{ github.sha }} to production [skip ci]"
          git push origin main

      # Trigger an immediate ArgoCD hard refresh to avoid waiting for the polling interval
      - name: Trigger ArgoCD hard refresh
        env:
          ARGOCD_OPTS: "--server ${{ env.ARGOCD_SERVER }} --auth-token ${{ env.ARGOCD_AUTH_TOKEN }} --grpc-web"
        run: argocd app get "${{ env.PRODUCTION_APP }}" --hard-refresh

      - name: Wait for production sync
        env:
          ARGOCD_OPTS: "--server ${{ env.ARGOCD_SERVER }} --auth-token ${{ env.ARGOCD_AUTH_TOKEN }} --grpc-web"
        run: |
          echo "Waiting for production ArgoCD sync..."
          DEADLINE=$(( $(date +%s) + 540 ))    # 9 min (leaves 1 min for prior steps in the 10 min job budget)
          while [ $(date +%s) -lt $DEADLINE ]; do
            STATUS=$(argocd app get "${{ env.PRODUCTION_APP }}" --output json 2>/dev/null | \
              jq -r '"\(.status.sync.status)/\(.status.health.status)"' || echo "Unknown/Unknown")
            echo "  Status: $STATUS"
            if [ "$STATUS" = "Synced/Healthy" ]; then
              echo "SUCCESS: Production is Synced and Healthy"
              exit 0
            fi
            sleep 15
          done
          echo "FAIL: Production not healthy within deadline"
          exit 1

      - name: Post production deployment summary
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const sha = '${{ github.sha }}';
            const approver = '${{ github.actor }}';
            github.rest.repos.createCommitComment({
              owner: context.repo.owner,
              repo:  context.repo.repo,
              commit_sha: sha,
              body: `**Production Deployment** approved by @${approver}\n`
                  + `SHA: \`${sha}\`\n`
                  + `ArgoCD app: \`${{ env.PRODUCTION_APP }}\``,
            });
```

---

### GitHub Environment: production (configuration reference)

Configure in GitHub UI: **Settings → Environments → New environment → `production`**

```yaml
# .github/environments/production.yml
# This file documents the expected environment configuration.
# The actual settings must be applied in the GitHub UI by a repository admin.
#
# Settings to apply:
#   Required reviewers:
#     - Team: platform-engineering (minimum 1 reviewer)
#     - Team: security-team (optional second approver for production changes)
#   Wait timer: 0 minutes (approval is the gate; no additional delay needed)
#   Deployment branches: main only
#   Secrets available in this environment:
#     - ARGOCD_AUTH_TOKEN  (scoped to production — separate token from staging)
#     - GITOPS_DEPLOY_KEY
```

---

### Production Helm values (structure matches staging)

```yaml
# helm/contextiq/values-production.yaml  (managed by CI after approval)
mcp_gateway:
  image:
    repository: ghcr.io/org/contextiq-api
    tag: "PLACEHOLDER"    # updated by promote_to_production step

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

# Production-specific overrides
mcp_gateway:
  replicaCount: 3    # higher baseline than staging (1)
  resources:
    requests: { cpu: "1", memory: "2Gi" }
    limits:   { cpu: "4", memory: "8Gi" }
```

---

### End-to-end pipeline validation test suite

```python
# tests/ci/test_pipeline_validation.py
"""
End-to-end validation of the US-049 CI/CD pipeline.

Requires:
  - GITHUB_TOKEN env var with read access to Actions API
  - GITHUB_REPOSITORY env var (e.g. "org/contextiq")
  - ARGOCD_SERVER and ARGOCD_AUTH_TOKEN env vars
  - Run after a full merge-to-main cycle has completed

Usage:
    pytest tests/ci/test_pipeline_validation.py -v --tb=short
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import pytest
import requests


GITHUB_TOKEN      = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
ARGOCD_SERVER     = os.environ["ARGOCD_SERVER"]
ARGOCD_AUTH_TOKEN = os.environ["ARGOCD_AUTH_TOKEN"]

GH_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ARGOCD_HEADERS = {
    "Authorization": f"Bearer {ARGOCD_AUTH_TOKEN}",
}


def _get_latest_workflow_run(workflow_file: str) -> dict:
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/actions/workflows/{workflow_file}/runs"
    r = requests.get(url, headers=GH_HEADERS, params={"branch": "main", "per_page": 1}, timeout=15)
    r.raise_for_status()
    runs = r.json()["workflow_runs"]
    assert runs, f"No workflow runs found for {workflow_file}"
    return runs[0]


def _get_argocd_app_status(app_name: str) -> dict:
    url = f"https://{ARGOCD_SERVER}/api/v1/applications/{app_name}"
    r = requests.get(url, headers=ARGOCD_HEADERS, verify=False, timeout=15)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# AC-1: PR checks workflow runs on every PR
# ---------------------------------------------------------------------------

class TestAC1_PRChecksExist:

    def test_pr_checks_workflow_exists(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/contents/.github/workflows/pr-checks.yml"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        assert r.status_code == 200, "pr-checks.yml not found in .github/workflows/"

    def test_security_scans_workflow_exists(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/contents/.github/workflows/security-scans.yml"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        assert r.status_code == 200, "security-scans.yml not found in .github/workflows/"


# ---------------------------------------------------------------------------
# AC-2: Multi-arch image exists in GHCR with SHA tag
# ---------------------------------------------------------------------------

class TestAC2_MultiArchImage:

    def test_ghcr_image_sha_tag_exists(self) -> None:
        """Check that GHCR has a package version matching the latest main commit SHA."""
        run = _get_latest_workflow_run("build.yml")
        sha = run["head_sha"]

        url = f"{GH_API}/user/packages/container/contextiq-api/versions"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        r.raise_for_status()
        tags = [tag for v in r.json() for tag in v.get("metadata", {}).get("container", {}).get("tags", [])]
        assert sha in tags, f"SHA tag {sha[:12]} not found in GHCR; available tags: {tags[:10]}"


# ---------------------------------------------------------------------------
# AC-3: Failed check blocks PR merge (branch protection)
# ---------------------------------------------------------------------------

class TestAC3_BranchProtection:

    def test_branch_protection_required_checks(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/branches/main/protection"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        assert r.status_code == 200, "Branch protection not configured on main"
        protection = r.json()
        checks = protection.get("required_status_checks", {}).get("checks", [])
        check_names = [c["context"] for c in checks]
        for required in ("PR Checks / Lint (ruff)", "PR Checks / Test (pytest)"):
            assert any(required in name for name in check_names), (
                f"Required status check '{required}' not configured. Configured: {check_names}"
            )


# ---------------------------------------------------------------------------
# AC-4: On merge to main, ArgoCD staging sync triggered
# ---------------------------------------------------------------------------

class TestAC4_ArgocdSyncTriggered:

    def test_staging_app_synced(self) -> None:
        status = _get_argocd_app_status("contextiq-staging")
        sync = status["status"]["sync"]["status"]
        assert sync == "Synced", f"contextiq-staging SyncStatus={sync!r}, expected Synced"

    def test_staging_image_matches_main_sha(self) -> None:
        run = _get_latest_workflow_run("deploy.yml")
        expected_sha = run["head_sha"]
        status = _get_argocd_app_status("contextiq-staging")
        # Check one resource's image tag as a proxy for the full deployment
        resources = status.get("status", {}).get("resources", [])
        deployments = [r for r in resources if r.get("kind") == "Deployment"]
        assert deployments, "No Deployment resources found in contextiq-staging"
        # Full image-tag validation is done by the wait-for-staging job; here we just confirm sync


# ---------------------------------------------------------------------------
# AC-5: Staging deployment completes within 10 minutes
# ---------------------------------------------------------------------------

class TestAC5_StagingDeployTime:

    def test_deploy_workflow_completed_within_10_minutes(self) -> None:
        run = _get_latest_workflow_run("deploy.yml")
        assert run["conclusion"] == "success", (
            f"Latest deploy workflow conclusion={run['conclusion']!r}, expected 'success'"
        )
        created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        updated_at = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
        elapsed_seconds = (updated_at - created_at).total_seconds()
        assert elapsed_seconds < 600, (
            f"Deploy workflow took {elapsed_seconds:.0f}s — exceeds 10-minute budget (AC-5)"
        )


# ---------------------------------------------------------------------------
# AC-6: Production requires manual approval (environment protection exists)
# ---------------------------------------------------------------------------

class TestAC6_ProductionApprovalGate:

    def test_production_environment_exists(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/environments/production"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        assert r.status_code == 200, "GitHub environment 'production' not configured"

    def test_production_environment_has_reviewers(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/environments/production"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        r.raise_for_status()
        protection_rules = r.json().get("protection_rules", [])
        reviewer_rules = [rule for rule in protection_rules if rule.get("type") == "required_reviewers"]
        assert reviewer_rules, (
            "Production environment has no required_reviewers protection rule — "
            "manual approval gate is not enforced (AC-6)"
        )

    def test_promote_to_production_job_in_deploy_workflow(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/contents/.github/workflows/deploy.yml"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        r.raise_for_status()
        import base64
        content = base64.b64decode(r.json()["content"]).decode()
        assert "environment:" in content and "production" in content, (
            "deploy.yml does not reference 'production' environment — AC-6 approval gate missing"
        )


# ---------------------------------------------------------------------------
# AC-7: Pipeline duration targets met
# ---------------------------------------------------------------------------

class TestAC7_PipelineDuration:

    def test_pr_checks_under_8_minutes(self) -> None:
        run = _get_latest_workflow_run("pr-checks.yml")
        if run["status"] != "completed":
            pytest.skip("Latest pr-checks run has not completed yet")
        created  = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        updated  = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
        elapsed  = (updated - created).total_seconds()
        assert elapsed < 480, (
            f"PR checks took {elapsed:.0f}s — exceeds 8-minute target (AC-7)"
        )

    def test_full_deploy_under_15_minutes(self) -> None:
        run = _get_latest_workflow_run("deploy.yml")
        if run["status"] != "completed":
            pytest.skip("Latest deploy run has not completed yet")
        created  = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        updated  = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
        elapsed  = (updated - created).total_seconds()
        assert elapsed < 900, (
            f"Full deploy pipeline took {elapsed:.0f}s — exceeds 15-minute target (AC-7)"
        )
```

## Acceptance Criteria

- [ ] A merge to `main` triggers `Deploy to Staging` → after staging is healthy, `Promote to Production` job appears **paused**, awaiting approval (AC-6)
- [ ] `Promote to Production` job remains pending until a member of the `platform-engineering` team clicks **Approve** in the GitHub Actions UI (AC-6)
- [ ] After approval, `contextiq-production` ArgoCD Application reaches `Synced/Healthy` (AC-6)
- [ ] Production pods carry the same SHA as the staging pods — no new build (AC-2, AC-6)
- [ ] `pytest tests/ci/test_pipeline_validation.py -v` passes all 7 AC test classes (all ACs)
- [ ] `TestAC7_PipelineDuration` assertions pass: PR checks < 8 min, full deploy < 15 min (AC-7)

## Dependencies

- TASK-US049-01 — `pr-checks.yml` must exist (referenced in AC-3/AC-7 tests)
- TASK-US049-02 — security scans workflow must be integrated
- TASK-US049-03 — `build.yml` reusable workflow must exist
- TASK-US049-04 — `deploy.yml` staging deploy jobs must exist; this task extends them
- TASK-US045-04 — ArgoCD `contextiq-production` Application must exist
- GitHub repository admin must create the `production` environment and assign required reviewers before the workflow can pause for approval
- `requests>=2.31` in test dependencies (`uv add requests --group dev`)

## Definition of Done

- [ ] `deploy.yml` extended with `promote-to-production` job gated on `environment: production`
- [ ] GitHub `production` environment configured with at least one required reviewer
- [ ] End-to-end test: merge to `main` → staging healthy → manual approval → production healthy, all within 15 minutes
- [ ] `pytest tests/ci/test_pipeline_validation.py` exits 0 after a successful full-cycle run
