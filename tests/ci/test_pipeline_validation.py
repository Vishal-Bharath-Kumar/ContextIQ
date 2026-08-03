"""
End-to-end validation of the US-049 CI/CD pipeline.

Validates all 7 acceptance criteria across the complete pipeline
(PR gates, build, security scans, staging deploy, production promotion).

Prerequisites
-------------
Environment variables required before running:

  GITHUB_TOKEN         GitHub PAT with read access to Actions and Packages APIs
  GITHUB_REPOSITORY    e.g. "myorg/contextiq"
  ARGOCD_SERVER        ArgoCD server hostname (no scheme), e.g. "argocd.contextiq.io"
  ARGOCD_AUTH_TOKEN    ArgoCD API token with read access to applications

Optional:
  ARGOCD_CA_BUNDLE     Path to a CA certificate bundle for TLS verification.
                       Defaults to system CA store.  Set to the path of your
                       ArgoCD TLS CA cert if using a private/self-signed cert.

Usage
-----
    pytest tests/ci/test_pipeline_validation.py -v --tb=short

Run after a full merge-to-main cycle has completed.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

import pytest
import requests

# ---------------------------------------------------------------------------
# Configuration (required env vars — fail fast with a clear message)
# ---------------------------------------------------------------------------
GITHUB_TOKEN      = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
ARGOCD_SERVER     = os.environ["ARGOCD_SERVER"]
ARGOCD_AUTH_TOKEN = os.environ["ARGOCD_AUTH_TOKEN"]

# BUG FIX: spec used verify=False (OWASP A02 — Cryptographic Failures).
# Defaulting to True uses the system CA store.  Override ARGOCD_CA_BUNDLE
# with a path to a custom CA cert for environments with private PKI.
_ca_bundle_env = os.environ.get("ARGOCD_CA_BUNDLE", "")
ARGOCD_TLS_VERIFY: bool | str = _ca_bundle_env if _ca_bundle_env else True

GH_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
ARGOCD_HEADERS = {
    "Authorization": f"Bearer {ARGOCD_AUTH_TOKEN}",
}

# Derived from GITHUB_REPOSITORY ("owner/repo")
_GH_OWNER, _GH_REPO = GITHUB_REPOSITORY.split("/", 1)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_latest_workflow_run(workflow_file: str) -> dict:
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/actions/workflows/{workflow_file}/runs"
    r = requests.get(
        url,
        headers=GH_HEADERS,
        params={"branch": "main", "per_page": 1},
        timeout=15,
    )
    r.raise_for_status()
    runs = r.json()["workflow_runs"]
    assert runs, f"No workflow runs found for {workflow_file}"
    return runs[0]


def _get_argocd_app_status(app_name: str) -> dict:
    url = f"https://{ARGOCD_SERVER}/api/v1/applications/{app_name}"
    # BUG FIX: spec used verify=False — replaced with ARGOCD_TLS_VERIFY which
    # defaults to True (system CA) and can be overridden via ARGOCD_CA_BUNDLE.
    r = requests.get(url, headers=ARGOCD_HEADERS, verify=ARGOCD_TLS_VERIFY, timeout=15)
    r.raise_for_status()
    return r.json()


def _get_package_tags(owner: str, package_name: str) -> list[str]:
    """Return all known GHCR tags for a container package.

    BUG FIX: spec used /user/packages/container/… which only works for
    packages owned by the authenticated user, not organisation-owned packages.
    Fixed by trying the /orgs/{owner}/… endpoint first, then /users/{owner}/…
    as a fallback, using the repository owner derived from GITHUB_REPOSITORY.
    """
    for scope in ("orgs", "users"):
        url = f"{GH_API}/{scope}/{owner}/packages/container/{package_name}/versions"
        r = requests.get(url, headers=GH_HEADERS, timeout=15)
        if r.status_code == 200:
            return [
                tag
                for version in r.json()
                for tag in version.get("metadata", {}).get("container", {}).get("tags", [])
            ]
    return []


def _elapsed_seconds(run: dict) -> float:
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    updated = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
    return (updated - created).total_seconds()


# ---------------------------------------------------------------------------
# AC-1: PR checks workflow exists and runs on every PR
# ---------------------------------------------------------------------------

class TestAC1PRChecksExist:

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

class TestAC2MultiArchImage:

    def test_ghcr_image_sha_tag_exists(self) -> None:
        """SHA tag for the latest main commit is present in GHCR."""
        run  = _get_latest_workflow_run("build.yml")
        sha  = run["head_sha"]
        # BUG FIX: use owner-aware package endpoint (org or user)
        tags = _get_package_tags(_GH_OWNER, "contextiq-api")
        assert sha in tags, (
            f"SHA tag {sha[:12]} not found in GHCR for contextiq-api; "
            f"available tags (first 10): {tags[:10]}"
        )


# ---------------------------------------------------------------------------
# AC-3: Failed check blocks PR merge (branch protection)
# ---------------------------------------------------------------------------

class TestAC3BranchProtection:

    def test_branch_protection_required_checks(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/branches/main/protection"
        r   = requests.get(url, headers=GH_HEADERS, timeout=15)
        assert r.status_code == 200, "Branch protection not configured on main"
        checks     = r.json().get("required_status_checks", {}).get("checks", [])
        check_names = [c["context"] for c in checks]
        for required in ("PR Checks / Lint (ruff)", "PR Checks / Test (pytest)"):
            assert any(required in name for name in check_names), (
                f"Required status check '{required}' not configured. "
                f"Configured checks: {check_names}"
            )


# ---------------------------------------------------------------------------
# AC-4: On merge to main, ArgoCD staging sync triggered
# ---------------------------------------------------------------------------

class TestAC4ArgocdSyncTriggered:

    def test_staging_app_synced(self) -> None:
        status = _get_argocd_app_status("contextiq-staging")
        sync   = status["status"]["sync"]["status"]
        assert sync == "Synced", (
            f"contextiq-staging SyncStatus={sync!r}, expected 'Synced'"
        )

    def test_staging_has_healthy_deployments(self) -> None:
        """Verify staging has active Deployment resources.

        BUG FIX: spec's test_staging_image_matches_main_sha claimed to check the
        image SHA but only asserted that Deployment resources exist (no SHA comparison).
        Renamed to accurately reflect what is actually asserted.  Full image-tag
        verification is done by the wait-for-staging CI job; here we check liveness.
        """
        status      = _get_argocd_app_status("contextiq-staging")
        resources   = status.get("status", {}).get("resources", [])
        deployments = [r for r in resources if r.get("kind") == "Deployment"]
        assert deployments, "No Deployment resources found in contextiq-staging"
        healthy = [d for d in deployments if d.get("health", {}).get("status") == "Healthy"]
        assert healthy, (
            f"No healthy Deployments in contextiq-staging; "
            f"resources: {[{'name': d.get('name'), 'health': d.get('health')} for d in deployments]}"
        )


# ---------------------------------------------------------------------------
# AC-5: Staging deployment completes within 10 minutes
# ---------------------------------------------------------------------------

class TestAC5StagingDeployTime:

    def test_deploy_workflow_succeeded(self) -> None:
        run = _get_latest_workflow_run("deploy.yml")
        assert run["conclusion"] == "success", (
            f"Latest deploy workflow conclusion={run['conclusion']!r}, expected 'success'"
        )

    def test_deploy_workflow_completed_within_10_minutes(self) -> None:
        run     = _get_latest_workflow_run("deploy.yml")
        if run["status"] != "completed":
            pytest.skip("Latest deploy run has not completed yet")
        elapsed = _elapsed_seconds(run)
        assert elapsed < 600, (
            f"Deploy workflow took {elapsed:.0f}s — exceeds 10-minute budget (AC-5)"
        )


# ---------------------------------------------------------------------------
# AC-6: Production requires manual approval (environment protection exists)
# ---------------------------------------------------------------------------

class TestAC6ProductionApprovalGate:

    def test_production_environment_exists(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/environments/production"
        r   = requests.get(url, headers=GH_HEADERS, timeout=15)
        assert r.status_code == 200, (
            "GitHub environment 'production' not configured. "
            "See .github/environments/production.yml for setup instructions."
        )

    def test_production_environment_has_required_reviewers(self) -> None:
        url   = f"{GH_API}/repos/{GITHUB_REPOSITORY}/environments/production"
        r     = requests.get(url, headers=GH_HEADERS, timeout=15)
        r.raise_for_status()
        rules = r.json().get("protection_rules", [])
        reviewer_rules = [rule for rule in rules if rule.get("type") == "required_reviewers"]
        assert reviewer_rules, (
            "Production environment has no required_reviewers protection rule — "
            "manual approval gate is not enforced (AC-6). "
            "Add reviewers in GitHub: Settings → Environments → production → Required reviewers."
        )

    def test_deploy_workflow_references_production_environment(self) -> None:
        url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/contents/.github/workflows/deploy.yml"
        r   = requests.get(url, headers=GH_HEADERS, timeout=15)
        r.raise_for_status()
        # BUG FIX: moved `import base64` to module level (was inside this method in spec)
        content = base64.b64decode(r.json()["content"]).decode()
        assert "environment:" in content and "production" in content, (
            "deploy.yml does not reference 'production' environment — "
            "AC-6 manual approval gate is missing"
        )


# ---------------------------------------------------------------------------
# AC-7: Pipeline duration targets met
# ---------------------------------------------------------------------------

class TestAC7PipelineDuration:

    def test_pr_checks_under_8_minutes(self) -> None:
        run = _get_latest_workflow_run("pr-checks.yml")
        if run["status"] != "completed":
            pytest.skip("Latest pr-checks run has not completed yet")
        elapsed = _elapsed_seconds(run)
        assert elapsed < 480, (
            f"PR checks took {elapsed:.0f}s — exceeds 8-minute target (AC-7)"
        )

    def test_full_deploy_under_15_minutes(self) -> None:
        run = _get_latest_workflow_run("deploy.yml")
        if run["status"] != "completed":
            pytest.skip("Latest deploy run has not completed yet")
        elapsed = _elapsed_seconds(run)
        assert elapsed < 900, (
            f"Full deploy pipeline took {elapsed:.0f}s — exceeds 15-minute target (AC-7)"
        )
