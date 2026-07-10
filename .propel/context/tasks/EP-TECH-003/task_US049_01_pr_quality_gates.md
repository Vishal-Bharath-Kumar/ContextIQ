# TASK-US049-01 — PR Quality Gates: Ruff Lint, Mypy Type-Check, and Pytest Unit Tests

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US049-01 |
| User Story | US-049 |
| Epic | EP-TECH-003 — CI/CD Pipeline & GitOps |
| Layer | CI/CD |
| Priority | P1 |
| Points | 2 |
| Status | Draft |

## Description

Create the `pr-checks.yml` GitHub Actions workflow that runs on every pull request targeting `main` (AC-1). It runs three parallel jobs — `lint` (ruff), `typecheck` (mypy), and `test` (pytest unit + integration) — and reports each as a separate status check. All three must pass before a PR can be merged (AC-3). Python dependency caching (`uv` pip cache) and pytest parallelisation (`pytest-xdist`) keep the total wall-clock time under 8 minutes (AC-7).

## Implementation Details

**Technology:** GitHub Actions, `uv` 0.4+, ruff 0.5+, mypy 1.10+, pytest 7+, pytest-xdist

**File locations:**
- `.github/workflows/pr-checks.yml` — main PR check workflow
- `pyproject.toml` — ruff + mypy configuration sections (already present; confirm settings)
- `.github/workflows/_python-setup.yml` — reusable step composite action for Python + uv setup

---

### Reusable Python setup composite action

```yaml
# .github/workflows/_python-setup.yml
# Composite action: install Python + uv + project dependencies with cache.
# Usage: steps: - uses: ./.github/workflows/_python-setup.yml
name: Python + uv setup
description: Install Python, uv, and project dependencies with full caching.

inputs:
  python-version:
    description: Python version to install
    default: "3.11"
  install-groups:
    description: Dependency groups to install (uv sync --group)
    default: "dev"

runs:
  using: composite
  steps:
    - name: Set up Python ${{ inputs.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ inputs.python-version }}

    - name: Install uv
      uses: astral-sh/setup-uv@v3
      with:
        version: "0.4.x"
        enable-cache: true    # persist uv download cache across runs

    - name: Install dependencies
      shell: bash
      run: |
        uv sync --frozen --group ${{ inputs.install-groups }}
      env:
        UV_CACHE_DIR: ${{ github.workspace }}/.uv-cache
```

---

### PR checks workflow

```yaml
# .github/workflows/pr-checks.yml
name: PR Checks

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

# Cancel in-progress runs for the same PR to avoid queueing stale builds
concurrency:
  group: pr-checks-${{ github.head_ref }}
  cancel-in-progress: true

env:
  PYTHON_VERSION: "3.11"
  UV_CACHE_DIR: ${{ github.workspace }}/.uv-cache

jobs:
  # -----------------------------------------------------------------------
  # Job 1: Lint (ruff)
  # AC-1: ruff lint — blocks PR merge on any violation (AC-3)
  # -----------------------------------------------------------------------
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-24.04
    timeout-minutes: 5    # AC-7: lint must complete in < 5 min

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python + uv
        uses: ./.github/workflows/_python-setup.yml
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          install-groups: dev

      # Restore ruff cache to skip unchanged files
      - name: Cache ruff
        uses: actions/cache@v4
        with:
          path: .ruff_cache
          key: ruff-${{ runner.os }}-${{ hashFiles('pyproject.toml', 'ruff.toml') }}-${{ github.sha }}
          restore-keys: ruff-${{ runner.os }}-${{ hashFiles('pyproject.toml', 'ruff.toml') }}-

      - name: Run ruff lint
        run: uv run ruff check . --output-format=github    # GitHub-annotated output

      - name: Run ruff format check
        run: uv run ruff format --check .

  # -----------------------------------------------------------------------
  # Job 2: Type-check (mypy)
  # AC-1: mypy strict mode — blocks PR merge on type errors (AC-3)
  # -----------------------------------------------------------------------
  typecheck:
    name: Type-check (mypy)
    runs-on: ubuntu-24.04
    timeout-minutes: 6    # AC-7

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python + uv
        uses: ./.github/workflows/_python-setup.yml
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          install-groups: dev

      # mypy cache: dramatically speeds up re-checks on unchanged modules
      - name: Cache mypy
        uses: actions/cache@v4
        with:
          path: .mypy_cache
          key: mypy-${{ runner.os }}-${{ env.PYTHON_VERSION }}-${{ hashFiles('pyproject.toml') }}-${{ github.sha }}
          restore-keys: mypy-${{ runner.os }}-${{ env.PYTHON_VERSION }}-${{ hashFiles('pyproject.toml') }}-

      - name: Run mypy
        run: uv run mypy src/ --strict --ignore-missing-imports

  # -----------------------------------------------------------------------
  # Job 3: Tests (pytest — unit + integration)
  # AC-1: pytest — blocks PR merge on any failure (AC-3)
  # -----------------------------------------------------------------------
  test:
    name: Test (pytest)
    runs-on: ubuntu-24.04
    timeout-minutes: 8    # AC-7: test job must complete in < 8 min

    services:
      # Lightweight test database — avoids needing a full cluster
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_USER:     testuser
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB:       contextiq_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd="pg_isready -U testuser"
          --health-interval=5s
          --health-timeout=5s
          --health-retries=5

      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd="redis-cli ping"
          --health-interval=5s
          --health-retries=5

    env:
      DATABASE_URL:    "postgresql+asyncpg://testuser:testpass@localhost:5432/contextiq_test"
      REDIS_URL:       "redis://localhost:6379/0"
      ENVIRONMENT:     "test"
      # Skip Vault/Keycloak/Kafka in unit test runs — mocked via pytest fixtures
      SKIP_EXTERNAL_SERVICES: "true"

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python + uv
        uses: ./.github/workflows/_python-setup.yml
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          install-groups: dev

      - name: Run Alembic migrations (test DB)
        run: uv run alembic upgrade head

      - name: Run unit tests
        # AC-7: -n auto parallelises tests across all available cores
        run: |
          uv run pytest tests/unit/ \
            -n auto \
            --tb=short \
            --junitxml=test-results/unit.xml \
            --cov=src \
            --cov-report=xml:coverage.xml \
            --cov-fail-under=80

      - name: Run integration tests
        run: |
          uv run pytest tests/integration/ \
            -n 4 \
            --tb=short \
            --junitxml=test-results/integration.xml \
            -m "not destructive"

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: test-results/
          retention-days: 7

      - name: Upload coverage report
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage.xml
          retention-days: 7

      # Annotate PR with test results (shows failures inline)
      - name: Publish test results
        if: always()
        uses: EnricoMi/publish-unit-test-result-action@v2
        with:
          files: test-results/**/*.xml
```

---

### `pyproject.toml` ruff + mypy configuration

```toml
# pyproject.toml — relevant sections (add to existing file)

[tool.ruff]
line-length    = 120
target-version = "py311"
exclude        = ["alembic/versions/"]

[tool.ruff.lint]
select = [
  "E",   # pycodestyle errors
  "W",   # pycodestyle warnings
  "F",   # pyflakes
  "I",   # isort
  "B",   # flake8-bugbear
  "C4",  # flake8-comprehensions
  "UP",  # pyupgrade
  "S",   # flake8-bandit (security)
  "ANN", # type annotation enforcement
]
ignore = [
  "ANN101",  # self annotation
  "ANN102",  # cls annotation
  "S101",    # assert usage (allowed in tests)
]

[tool.mypy]
python_version         = "3.11"
strict                 = true
ignore_missing_imports = true
plugins                = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths    = ["tests"]
markers      = [
  "destructive: tests that modify cluster state (requires --run-destructive flag)",
  "slow: tests with wall-clock time > 30s",
]
addopts = "--strict-markers"
```

---

### Required status checks (GitHub Branch Protection)

Configure via GitHub repository settings → Branch protection rules → `main`:

```
Required status checks:
  ✓ PR Checks / Lint (ruff)         ← lint job
  ✓ PR Checks / Type-check (mypy)   ← typecheck job
  ✓ PR Checks / Test (pytest)       ← test job

Options:
  ✓ Require status checks to pass before merging (AC-3)
  ✓ Require branches to be up to date before merging
  ✓ Do not allow bypassing the above settings
```

## Acceptance Criteria

- [ ] Every PR to `main` triggers the `PR Checks` workflow automatically (AC-1)
- [ ] A PR with a ruff lint violation shows `PR Checks / Lint (ruff)` as failed and blocks merge (AC-3)
- [ ] A PR with a failing test shows `PR Checks / Test (pytest)` as failed and blocks merge (AC-3)
- [ ] Workflow completes in < 8 minutes on a warm cache run (AC-7)
- [ ] `test-results/` artifact uploaded and test annotations visible in the PR (AC-1)
- [ ] Coverage gate: pytest exits non-zero if line coverage drops below 80%

## Dependencies

- Existing `pyproject.toml` with `[tool.ruff]` and `[tool.mypy]` sections (confirm before running)
- `uv.lock` committed to the repository so `uv sync --frozen` is deterministic
- GitHub repository branch protection rules must be configured by a repo admin after workflow is merged

## Definition of Done

- [ ] `.github/workflows/pr-checks.yml` merged to `main`
- [ ] Branch protection rules configured with 3 required status checks
- [ ] First PR after setup shows all 3 status checks passing within 8 minutes
