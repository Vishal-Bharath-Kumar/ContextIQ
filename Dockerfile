# syntax=docker/dockerfile:1.9

ARG PYTHON_VERSION=3.11
ARG GIT_SHA=unknown
ARG GIT_REF=unknown

# ---- Stage 1: dependency builder ----------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=180

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

# Pre-cache tiktoken encoding to avoid online download at startup
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" 2>/dev/null || true

# ---- Stage 2: runtime image ---------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# BUG FIX: ARG variables declared before the first FROM are only in scope for
# FROM instructions.  They are NOT available to ENV, RUN, COPY etc. inside a
# stage unless explicitly re-declared after that stage's FROM.  Without these
# two ARG lines, ${GIT_SHA} and ${GIT_REF} in the ENV instruction below would
# silently expand to empty strings, leaving GIT_SHA="" in the final image.
ARG GIT_SHA=unknown
ARG GIT_REF=unknown

# Non-root user (OWASP A05 — Security Misconfiguration)
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy the virtual environment and application from builder stage
COPY --from=builder --chown=appuser:appgroup /app/.venv    /app/.venv
COPY --from=builder --chown=appuser:appgroup /app/src      /app/src
COPY --from=builder --chown=appuser:appgroup /app/alembic  /app/alembic
COPY --from=builder --chown=appuser:appgroup /app/alembic.ini /app/alembic.ini

# Bake git metadata into the image for the runtime version endpoint
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GIT_SHA=${GIT_SHA} \
    GIT_REF=${GIT_REF}

USER appuser

# Source Vault-injected credentials before starting (see TASK-US047-03).
# The \<newline> sequences are Dockerfile line continuations — after parsing
# the ENTRYPOINT becomes a single-line shell command string.
ENTRYPOINT ["/bin/sh", "-c", "\
  for f in /vault/secrets/*.env; do [ -f \"$f\" ] && . \"$f\"; done; \
  exec python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 \
"]

EXPOSE 8000
