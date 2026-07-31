#!/bin/sh
# gen-certs.sh — Generate all TLS certificates for local development.
# Runs as a one-shot Docker container (cert-init service).
# Certs are stored in the shared `tls-certs` volume at /tls.
#
# Certificate layout:
#   /tls/ca.crt                 — Local CA certificate (shared trust anchor)
#   /tls/ca.key                 — CA private key
#   /tls/redis.crt              — Redis server certificate
#   /tls/redis.key              — Redis server private key (owned by uid 999)
#   /tls/redis-sentinel.crt     — Redis Sentinel server certificate
#   /tls/redis-sentinel.key     — Redis Sentinel private key (owned by uid 999)
#   /tls/postgres.crt           — PostgreSQL server certificate
#   /tls/postgres.key           — PostgreSQL server private key (owned by uid 999)
#   /tls/kafka.crt              — Kafka broker certificate
#   /tls/kafka.key              — Kafka broker private key (owned by uid 1001)
#   /tls/kafka.keystore.pem     — Bitnami Kafka PEM keystore (key + cert)
#   /tls/kafka.truststore.pem   — Bitnami Kafka PEM truststore (CA cert)
#   /tls/tls.crt                — Client certificate (app containers)
#   /tls/tls.key                — Client private key (owned by uid 10001)

set -e

TLS_DIR="/tls"

# Skip if CA already exists — certs survive container restarts via named volume
if [ -f "$TLS_DIR/ca.crt" ]; then
    echo "[cert-init] Certificates already exist — skipping generation."
    exit 0
fi

echo "[cert-init] Generating local CA and TLS certificates..."

# ── Certificate Authority ────────────────────────────────────────────────────
openssl genrsa -out "$TLS_DIR/ca.key" 4096 2>/dev/null
openssl req -new -x509 -days 3650 \
    -key "$TLS_DIR/ca.key" \
    -out "$TLS_DIR/ca.crt" \
    -subj "/CN=ContextIQ Local CA/O=ContextIQ Dev/C=US" 2>/dev/null
echo "[cert-init] CA created."

# ── Helper: create a server cert signed by our CA, with SAN ─────────────────
create_server_cert() {
    local name="$1"
    local san="$2"
    local ext_file="$TLS_DIR/${name}.ext"

    printf "[req]\ndistinguished_name=req\n[SAN]\nsubjectAltName=%s\n" "$san" \
        > "$ext_file"

    openssl genrsa -out "$TLS_DIR/${name}.key" 2048 2>/dev/null
    openssl req -new \
        -key "$TLS_DIR/${name}.key" \
        -out "$TLS_DIR/${name}.csr" \
        -subj "/CN=${name}/O=ContextIQ Dev/C=US" 2>/dev/null
    openssl x509 -req -days 3650 \
        -in "$TLS_DIR/${name}.csr" \
        -CA "$TLS_DIR/ca.crt" \
        -CAkey "$TLS_DIR/ca.key" \
        -CAcreateserial \
        -extfile "$ext_file" \
        -extensions SAN \
        -out "$TLS_DIR/${name}.crt" 2>/dev/null

    rm -f "$ext_file" "$TLS_DIR/${name}.csr"
    echo "[cert-init] ${name} certificate created."
}

# ── Server Certificates ──────────────────────────────────────────────────────
create_server_cert redis          "DNS:redis,DNS:localhost,IP:127.0.0.1"
create_server_cert redis-sentinel "DNS:redis-sentinel,DNS:localhost,IP:127.0.0.1"
create_server_cert postgres       "DNS:postgres,DNS:localhost,IP:127.0.0.1"
create_server_cert kafka          "DNS:kafka,DNS:localhost,IP:127.0.0.1"

# ── Client Certificate (for app containers at /tls/tls.crt + /tls/tls.key) ──
create_server_cert client "DNS:app,DNS:localhost"
cp "$TLS_DIR/client.crt" "$TLS_DIR/tls.crt"
cp "$TLS_DIR/client.key" "$TLS_DIR/tls.key"
echo "[cert-init] Client certificate (tls.crt / tls.key) created."

# ── Bitnami Kafka PEM bundles ────────────────────────────────────────────────
# kafka.keystore.pem = private key + certificate (Bitnami PEM keystore format)
cat "$TLS_DIR/kafka.key" "$TLS_DIR/kafka.crt" > "$TLS_DIR/kafka.keystore.pem"
# kafka.truststore.pem = CA certificate (Bitnami PEM truststore format)
cp "$TLS_DIR/ca.crt" "$TLS_DIR/kafka.truststore.pem"
echo "[cert-init] Kafka PEM bundles created."

# ── File permissions ─────────────────────────────────────────────────────────
# Public certs: world-readable
chmod 644 "$TLS_DIR"/*.crt "$TLS_DIR"/*.pem 2>/dev/null || true

# Private keys: readable by the owning service process only
# Redis (official image uid=999, gid=999 on Debian-based)
chmod 640 "$TLS_DIR/redis.key" "$TLS_DIR/redis-sentinel.key"
chown 999:999 "$TLS_DIR/redis.key" "$TLS_DIR/redis-sentinel.key"

# PostgreSQL (official image uid=999, gid=999 on Debian-based)
chmod 640 "$TLS_DIR/postgres.key"
chown 999:999 "$TLS_DIR/postgres.key"

# Kafka (Bitnami image uid=1001, gid=1001)
chmod 640 "$TLS_DIR/kafka.key" "$TLS_DIR/kafka.keystore.pem"
chown 1001:1001 "$TLS_DIR/kafka.key" "$TLS_DIR/kafka.keystore.pem"

# App containers (appuser uid=10001, gid=10001)
chmod 640 "$TLS_DIR/tls.key" "$TLS_DIR/client.key"
chown 10001:10001 "$TLS_DIR/tls.key" "$TLS_DIR/client.key"

# CA key stays root-owned
chmod 600 "$TLS_DIR/ca.key"

echo "[cert-init] All certificates generated and permissions set."
