# TASK-US049-03 — Multi-arch Docker Image Build and Push to GitHub Container Registry

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US049-03 |
| User Story | US-049 |
| Epic | EP-TECH-003 — CI/CD Pipeline & GitOps |
| Layer | CI/CD |
| Priority | P1 |
| Points | 2 |
| Status | Draft |

## Description

Add a `build` job to the PR/merge workflow that uses Docker Buildx to produce multi-architecture images (`linux/amd64` and `linux/arm64`) and pushes them to GitHub Container Registry (ghcr.io) with the image tag set to the Git SHA (AC-2). Layer caching via GitHub Actions cache (`type=gha`) keeps rebuild times inside the pipeline duration budget (AC-7). On pull requests, images are built and pushed with a `pr-<number>` tag for Trivy scanning (TASK-US049-02). On merge to `main`, the same job runs again and pushes the `:git-sha` + `:latest` tags.

## Implementation Details

**Technology:** Docker Buildx, GitHub Actions `docker/build-push-action`, GHCR (`ghcr.io`)

**File locations:**
- `.github/workflows/build.yml` — reusable build workflow (`workflow_call`)
- `.github/workflows/pr-checks.yml` — calls `build.yml` on PR
- `.github/workflows/deploy.yml` — calls `build.yml` on merge (TASK-US049-04)
- `Dockerfile` — multi-stage build (confirm existing; add `TARGETPLATFORM` support)
- `.dockerignore` — ensure `.git`, `tests/`, docs excluded for lean image

---

### Reusable build workflow

```yaml
# .github/workflows/build.yml
name: Build Docker Image

on:
  workflow_call:
    inputs:
      push:
        description: "Push image to GHCR (true on merge; false on draft PRs)"
        type:    bool
        default: true
      tag-suffix:
        description: "Additional tag suffix appended to the SHA tag (e.g. pr-123)"
        type:    string
        default: ""
    outputs:
      image-ref:
        description: "Full image reference including SHA tag"
        value:        ${{ jobs.build.outputs.image-ref }}
      image-digest:
        description: "Image digest (sha256:...)"
        value:        ${{ jobs.build.outputs.image-digest }}

jobs:
  build:
    name: Build & Push (${{ matrix.service }})
    runs-on: ubuntu-24.04
    timeout-minutes: 12    # AC-7: build must complete well within 15 min deploy budget

    strategy:
      fail-fast: false
      matrix:
        # Build each backend service image independently for layer cache efficiency
        service:
          - name:       contextiq-api
            context:    .
            dockerfile: Dockerfile
          - name:       contextiq-agent-worker
            context:    .
            dockerfile: Dockerfile.agent
          - name:       contextiq-indexing
            context:    .
            dockerfile: Dockerfile.indexing

    permissions:
      contents: read
      packages: write    # required to push to ghcr.io

    outputs:
      image-ref:    ${{ steps.meta.outputs.tags }}
      image-digest: ${{ steps.build.outputs.digest }}

    steps:
      - uses: actions/checkout@v4

      # AC-2: Set up Buildx for multi-arch (amd64 + arm64)
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
        with:
          driver-opts: |
            image=moby/buildkit:v0.15.0
            network=host

      # arm64 emulation via QEMU (required to build arm64 on amd64 runners)
      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
        with:
          platforms: linux/amd64,linux/arm64

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}    # GITHUB_TOKEN has packages:write on the repo

      # Generate image tags: SHA (always), branch name, latest (on main only)
      - name: Extract image metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/${{ matrix.service.name }}
          tags: |
            # AC-2: image tag = git SHA (immutable, used by ArgoCD for deployment tracking)
            type=sha,format=long,prefix=
            # Branch name tag (human-readable for debugging)
            type=ref,event=branch
            # PR tag — used by Trivy scan (TASK-US049-02)
            type=ref,event=pr,prefix=pr-
            # latest tag — only on pushes to main
            type=raw,value=latest,enable={{is_default_branch}}
          labels: |
            org.opencontainers.image.title=${{ matrix.service.name }}
            org.opencontainers.image.vendor=ContextIQ
            org.opencontainers.image.revision=${{ github.sha }}

      # AC-2: Build multi-arch image and push
      - name: Build and push
        id: build
        uses: docker/build-push-action@v6
        with:
          context:    ${{ matrix.service.context }}
          file:       ${{ matrix.service.dockerfile }}
          platforms:  linux/amd64,linux/arm64
          push:       ${{ inputs.push }}
          tags:       ${{ steps.meta.outputs.tags }}
          labels:     ${{ steps.meta.outputs.labels }}
          # AC-7: GHA cache for layer reuse across runs — critical for 12 min budget
          cache-from: type=gha,scope=${{ matrix.service.name }}
          cache-to:   type=gha,scope=${{ matrix.service.name }},mode=max
          # Build args: bake the git SHA into the image for runtime version reporting
          build-args: |
            GIT_SHA=${{ github.sha }}
            GIT_REF=${{ github.ref_name }}

      # Attest the build provenance (SLSA level 3) — OWASP supply chain best practice
      - name: Attest image provenance
        if: ${{ inputs.push }}
        uses: actions/attest-build-provenance@v1
        with:
          subject-name:   ghcr.io/${{ github.repository_owner }}/${{ matrix.service.name }}
          subject-digest: ${{ steps.build.outputs.digest }}
          push-to-registry: true

      - name: Output image details
        run: |
          echo "Image: ghcr.io/${{ github.repository_owner }}/${{ matrix.service.name }}"
          echo "Tags: ${{ steps.meta.outputs.tags }}"
          echo "Digest: ${{ steps.build.outputs.digest }}"
```

---

### Call build from `pr-checks.yml`

```yaml
# .github/workflows/pr-checks.yml  (extend — add build job, called before security-scans)

  build:
    name: Build Docker Images
    uses: ./.github/workflows/build.yml
    with:
      push: true         # push PR-tagged image so Trivy (TASK-US049-02) can pull it
      tag-suffix: pr-${{ github.event.number }}
    permissions:
      contents: read
      packages: write
```

---

### Multi-stage Dockerfile with TARGETPLATFORM support

```dockerfile
# Dockerfile  (canonical service Dockerfile — multi-stage for lean image)
# syntax=docker/dockerfile:1.9

ARG PYTHON_VERSION=3.11
ARG GIT_SHA=unknown
ARG GIT_REF=unknown

# ---- Stage 1: dependency builder ----------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Copy lockfile first — layer is cached unless dependencies change
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Stage 2: runtime image ---------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# Non-root user (OWASP A05 — Security Misconfiguration)
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy the virtual environment from builder stage
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/src   /app/src
COPY --from=builder --chown=appuser:appgroup /app/alembic /app/alembic
COPY --from=builder --chown=appuser:appgroup /app/alembic.ini /app/alembic.ini

# Bake git metadata into image for runtime version endpoint
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GIT_SHA=${GIT_SHA} \
    GIT_REF=${GIT_REF}

USER appuser

# Source Vault-injected credentials before starting (TASK-US047-03)
ENTRYPOINT ["/bin/sh", "-c", "\
  for f in /vault/secrets/*.env; do [ -f \"$f\" ] && . \"$f\"; done; \
  exec python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 \
"]

EXPOSE 8000
```

---

### `.dockerignore`

```
# .dockerignore — exclude files that must not be in the image
.git/
.github/
.mypy_cache/
.ruff_cache/
.uv-cache/
__pycache__/
*.pyc
tests/
docs/
*.md
*.env
*.env.*
helm/
k8s/
argocd/
scripts/
```

## Acceptance Criteria

- [ ] PR workflow `build` job completes and shows `ghcr.io/…/contextiq-api:pr-<n>` in the logs (AC-2)
- [ ] `docker manifest inspect ghcr.io/…/contextiq-api:<sha>` shows both `linux/amd64` and `linux/arm64` digests (AC-2)
- [ ] Image tag matches `github.sha` exactly (e.g. `a3f9b1c2…`) — not branch name or `latest` (AC-2)
- [ ] On re-run with no code changes, build completes in < 3 minutes (GHA cache hit) (AC-7)
- [ ] Image contains no root-owned processes: `docker run --rm … whoami` returns `appuser` (OWASP A05)
- [ ] SLSA provenance attestation is present: `gh attestation verify ghcr.io/…/contextiq-api:<sha>`

## Dependencies

- TASK-US049-01 — `pr-checks.yml` must exist to call `build.yml`
- TASK-US049-02 — Trivy scan job `needs: build` and uses `image-ref` output from this task
- `GITHUB_TOKEN` secret is automatic — no manual configuration needed for GHCR push
- Existing `Dockerfile` in repository root must be reviewed for `TARGETPLATFORM` compatibility

## Definition of Done

- [ ] `.github/workflows/build.yml` merged to `main`
- [ ] Multi-arch manifest visible on `ghcr.io` for the repository
- [ ] `pr-checks.yml` `build` job integrated and passing on a test PR
