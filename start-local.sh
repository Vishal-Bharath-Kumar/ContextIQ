#!/usr/bin/env bash
# start-local.sh — One-command local development setup for ContextIQ
#
# Usage:
#   chmod +x start-local.sh
#   ./start-local.sh
#
# What it does:
#   1. Copies .env.local → .env (if .env doesn't exist)
#   2. Builds application Docker images
#   3. Starts all infrastructure and application services
#   4. Waits for the API gateway to be ready
#   5. Prints service URLs

set -euo pipefail

COMPOSE="docker compose"

# ── Step 1: Environment file ──────────────────────────────────────────────────
if [ ! -f .env ]; then
    echo "→ Creating .env from .env.local (edit .env to add your API keys)"
    cp .env.local .env
else
    echo "→ .env already exists — using existing file"
fi

# ── Step 2: Build application images ─────────────────────────────────────────
echo ""
echo "→ Building application images (this may take a few minutes on first run)..."
$COMPOSE build --parallel api agent-worker indexing db-migrate kafka-init

# ── Step 3: Pull infrastructure images ───────────────────────────────────────
echo ""
echo "→ Pulling infrastructure images..."
$COMPOSE pull --ignore-pull-failures postgres redis kafka qdrant neo4j minio keycloak jaeger 2>/dev/null || true

# ── Step 4: Start infrastructure services ─────────────────────────────────────
echo ""
echo "→ Starting infrastructure services..."
$COMPOSE up -d cert-init
$COMPOSE up -d postgres redis kafka qdrant neo4j minio keycloak jaeger

# ── Step 5: Wait for postgres to be ready ─────────────────────────────────────
echo ""
echo "→ Waiting for PostgreSQL to be ready..."
until $COMPOSE exec -T postgres pg_isready -U contextiq -d contextiq >/dev/null 2>&1; do
    printf '.'
    sleep 2
done
echo " ready!"

# ── Step 6: Run database migrations ───────────────────────────────────────────
echo ""
echo "→ Running database migrations..."
$COMPOSE up --no-log-prefix db-migrate
echo "   Migrations complete."

# ── Step 7: Start Redis Sentinel ──────────────────────────────────────────────
echo ""
echo "→ Starting Redis Sentinel..."
$COMPOSE up -d redis-sentinel

# ── Step 8: Bootstrap Kafka topics ────────────────────────────────────────────
echo ""
echo "→ Bootstrapping Kafka topics (waiting for Kafka to be ready)..."
$COMPOSE up --no-log-prefix kafka-init
echo "   Kafka topics ready."

# ── Step 9: Create MinIO buckets ──────────────────────────────────────────────
echo ""
echo "→ Creating MinIO buckets..."
$COMPOSE up --no-log-prefix minio-init
echo "   MinIO buckets ready."

# ── Step 10: Start application services ──────────────────────────────────────
echo ""
echo "→ Starting application services..."
$COMPOSE up -d api agent-worker indexing admin-portal

# ── Step 11: Wait for API to be ready ────────────────────────────────────────
echo ""
echo "→ Waiting for API gateway to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/healthz >/dev/null 2>&1; then
        echo " ready!"
        break
    fi
    printf '.'
    sleep 3
done

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  ContextIQ is running locally!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Service URLs:"
echo "    API Gateway    →  http://localhost:8000      (docs: /docs)"
echo "    Agent Worker   →  http://localhost:8001"
echo "    Admin Portal   →  http://localhost:3000"
echo "    Keycloak       →  http://localhost:8080/auth  (admin/admin)"
echo "    Jaeger UI      →  http://localhost:16686"
echo "    MinIO Console  →  http://localhost:9001       (contextiq/contextiq_dev)"
echo "    Qdrant UI      →  http://localhost:6333/dashboard"
echo "    Neo4j Browser  →  http://localhost:7474       (neo4j/contextiq_dev)"
echo ""
echo "  Get a JWT token for API testing:"
echo "    curl -s -X POST http://localhost:8080/auth/realms/contextiq/protocol/openid-connect/token \\"
echo "      -d 'grant_type=password&client_id=contextiq-mcp-gateway&username=admin&password=admin' \\"
echo "      | python3 -m json.tool | grep access_token"
echo ""
echo "  Logs:  docker compose logs -f api"
echo "  Stop:  docker compose down"
echo "════════════════════════════════════════════════════════════"
