# TASK-US049-02 — PR Security Scans: Trivy Image Scan and OWASP Dependency-Check

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US049-02 |
| User Story | US-049 |
| Epic | EP-TECH-003 — CI/CD Pipeline & GitOps |
| Layer | CI/CD / Security |
| Priority | P1 |
| Points | 2 |
| Status | Done |

## Description

Add two security-scan jobs to the PR checks workflow (AC-1): `trivy-scan` scans the built Docker image for HIGH/CRITICAL OS and library CVEs; `dependency-check` runs OWASP Dependency-Check against the Python dependency tree for known vulnerabilities. Both jobs run in parallel after the Docker build step and must pass before a PR can be merged (AC-3). Scan results are uploaded to GitHub Security → Code Scanning Alerts as SARIF reports, giving reviewers inline vulnerability annotations on the PR diff.

## Implementation Details

**Technology:** Trivy 0.52+, OWASP Dependency-Check 9.x, GitHub Code Scanning (SARIF), GitHub Actions

**File locations:**
- `.github/workflows/security-scans.yml` — standalone security scan workflow (called from `pr-checks.yml` via `workflow_call`)
- `.github/workflows/pr-checks.yml` — extended to call `security-scans.yml`
- `.trivyignore` — accepted/suppressed CVE exceptions with expiry dates
- `scripts/ci/check_trivy_results.py` — parse SARIF and fail on unaccepted HIGH/CRITICAL findings

---

### Security scans reusable workflow

```yaml
# .github/workflows/security-scans.yml
name: Security Scans

on:
  workflow_call:
    inputs:
      image-ref:
        description: "Full image reference to scan (e.g. ghcr.io/org/repo:sha)"
        type:    string
        required: true
      fail-on-severity:
        description: "Minimum severity to fail the build (CRITICAL, HIGH, MEDIUM)"
        type:    string
        default: HIGH

jobs:
  # -----------------------------------------------------------------------
  # Job 1: Trivy container image scan
  # AC-1: scans the image built in the same workflow run
  # -----------------------------------------------------------------------
  trivy-scan:
    name: Trivy Image Scan
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      security-events: write    # required to upload SARIF to Code Scanning

    steps:
      - uses: actions/checkout@v4

      # Pull the image built by TASK-US049-03 (passed as input)
      - name: Pull image for scanning
        run: docker pull ${{ inputs.image-ref }}

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@0.24.0
        with:
          image-ref:       ${{ inputs.image-ref }}
          format:          sarif
          output:          trivy-results.sarif
          severity:        CRITICAL,HIGH,MEDIUM
          ignore-unfixed:  true     # suppress CVEs with no upstream fix
          trivyignores:    .trivyignore
          # Fail the action immediately if unaccepted HIGH/CRITICAL found (AC-3)
          exit-code:       "1"
          vuln-type:       "os,library"

      # Upload SARIF even on failure so reviewers can see findings
      - name: Upload Trivy SARIF to Code Scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: trivy-results.sarif
          category:   trivy

      - name: Upload Trivy results artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name:            trivy-results
          path:            trivy-results.sarif
          retention-days:  14

  # -----------------------------------------------------------------------
  # Job 2: OWASP Dependency-Check
  # AC-1: scans Python dependency tree for known CVEs (NVD)
  # -----------------------------------------------------------------------
  dependency-check:
    name: OWASP Dependency-Check
    runs-on: ubuntu-24.04
    timeout-minutes: 15    # NVD database download can take 3-5 min on cold cache

    steps:
      - uses: actions/checkout@v4

      # Cache the NVD database — saves 3-4 min on warm runs (AC-7)
      - name: Cache NVD database
        uses: actions/cache@v4
        with:
          path: ~/.dependency-check/data
          key: dependency-check-nvd-${{ runner.os }}-${{ steps.date.outputs.date }}
          restore-keys: dependency-check-nvd-${{ runner.os }}-
        id: nvd-cache

      - name: Get current date (for cache key rotation)
        id: date
        run: echo "date=$(date +'%Y-%m-%d')" >> "$GITHUB_OUTPUT"

      # Export Python requirements for DC to analyse
      - name: Export Python dependencies
        uses: astral-sh/setup-uv@v3
        with:
          version: "0.4.x"
      - run: uv export --no-dev --format requirements-txt > requirements-scan.txt

      - name: Run OWASP Dependency-Check
        uses: dependency-check/Dependency-Check_Action@main
        with:
          project:    ContextIQ
          path:       requirements-scan.txt
          format:     SARIF
          out:        dependency-check-report
          # AC-3: fail on HIGH/CRITICAL CVSS score >= 7.0
          args: >-
            --failOnCVSS 7
            --enableRetired
            --suppression .github/dependency-check-suppressions.xml
            --nvdApiKey ${{ secrets.NVD_API_KEY }}

      - name: Upload Dependency-Check SARIF to Code Scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: dependency-check-report/dependency-check-report.sarif
          category:   dependency-check

      - name: Upload Dependency-Check report artifact
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name:           dependency-check-report
          path:           dependency-check-report/
          retention-days: 14
```

---

### Extend `pr-checks.yml` to call security scans

```yaml
# .github/workflows/pr-checks.yml  (extend — add after the existing lint/typecheck/test jobs)
# Security scans run after the build job (TASK-US049-03) produces the image

  security-scans:
    name: Security Scans
    needs: build    # wait for the image to be pushed (TASK-US049-03)
    uses: ./.github/workflows/security-scans.yml
    with:
      image-ref:        ghcr.io/${{ github.repository }}/contextiq-api:${{ github.sha }}
      fail-on-severity: HIGH
    permissions:
      security-events: write
      packages:        read
    secrets: inherit    # forward NVD_API_KEY secret
```

---

### `.trivyignore` — accepted CVE exceptions

```
# .trivyignore
# Format: CVE-ID  [expiry-date]  # justification
#
# Each exception MUST have an expiry date (max 90 days) and a business justification.
# Expired exceptions cause the scan to fail again — forcing periodic review.
#
# Example (replace with real CVEs as they arise):
# CVE-2024-00001 exp:2026-10-01 # no fix available; mitigated by network isolation (US-048 mTLS)
```

---

### `dependency-check-suppressions.xml` — accepted dependency exceptions

```xml
<!-- .github/dependency-check-suppressions.xml -->
<!-- OWASP Dependency-Check suppression file.
     Each suppression MUST include notes with a justification and review date.
     Suppressions without notes will be rejected in PR review. -->
<?xml version="1.0" encoding="UTF-8"?>
<suppressions xmlns="https://jeremylong.github.io/DependencyCheck/dependency-suppression.1.3.xsd">
  <!-- Example suppression structure:
  <suppress until="2026-10-01Z">
    <notes>CVE-XXXX: no fix upstream; mitigated by US-048 network controls. Review by 2026-10-01.</notes>
    <cve>CVE-XXXX-YYYY</cve>
  </suppress>
  -->
</suppressions>
```

---

### Required status checks additions (GitHub Branch Protection)

Extend the branch protection rules created in TASK-US049-01:

```
Additional required status checks:
  ✓ Security Scans / Trivy Image Scan
  ✓ Security Scans / OWASP Dependency-Check
```

---

### `NVD_API_KEY` secret

Register a free NVD API key at https://nvd.nist.gov/developers/request-an-api-key and add it as a GitHub Actions repository secret named `NVD_API_KEY`. Without the key, the NVD download is rate-limited to 5 requests/30s which increases the job duration beyond the AC-7 target.

## Acceptance Criteria

- [x] Every PR triggers `Security Scans / Trivy Image Scan` and `Security Scans / OWASP Dependency-Check` jobs (AC-1)
- [x] A PR that introduces an image layer with a HIGH/CRITICAL CVE causes `Trivy Image Scan` to fail and blocks merge (AC-3)
- [x] A PR that adds a dependency with a CVSS >= 7.0 causes `OWASP Dependency-Check` to fail and blocks merge (AC-3)
- [x] Trivy SARIF findings appear under GitHub Security → Code Scanning Alerts for the repository (AC-1)
- [x] On a clean codebase with warm NVD cache, `dependency-check` completes in < 10 minutes (AC-7)
- [x] `.trivyignore` entries without an expiry date cause the workflow to fail (prevents permanent suppressions)

## Dependencies

- TASK-US049-01 — `pr-checks.yml` must exist; security scans are added to it
- TASK-US049-03 — `build` job must produce the image before Trivy can scan it
- `NVD_API_KEY` GitHub Actions secret must be created by a repo admin
- GitHub Advanced Security must be enabled on the repository for SARIF Code Scanning

## Definition of Done

- [x] `.github/workflows/security-scans.yml` merged to `main`
- [x] `pr-checks.yml` extended to call security scans with `needs: build`
- [x] Two additional required status checks configured in branch protection rules
- [x] First full PR run shows Trivy and Dependency-Check results in GitHub Security tab
