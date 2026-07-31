#!/bin/bash
# 01-ssl.sh — Generate a self-signed SSL certificate for PostgreSQL and enable
# SSL via postgresql.conf.
#
# Runs as the postgres user inside docker-entrypoint-initdb.d, which executes
# against a TEMPORARY bootstrap server (docker_temp_server_start) that forwards
# the same extra args as the real server. SSL config must NOT be passed via
# the container command/CLI flags, because the temp server starts before this
# script runs and would fail to find the not-yet-generated cert (chicken-and-
# egg). Instead this script appends the SSL directives to postgresql.conf so
# they only take effect on the *next* server start — i.e. the real one, once
# docker_temp_server_stop has shut the temp server back down.

set -e

CERT_FILE="$PGDATA/server.crt"
KEY_FILE="$PGDATA/server.key"

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "[postgres-init] SSL certificate already exists — skipping."
    exit 0
fi

echo "[postgres-init] Generating self-signed SSL certificate..."
openssl req -new -x509 -days 3650 -nodes \
    -subj "/CN=postgres/O=ContextIQ Dev/C=US" \
    -out "$CERT_FILE" \
    -keyout "$KEY_FILE" 2>/dev/null

chmod 600 "$KEY_FILE"
echo "[postgres-init] SSL certificate generated at $CERT_FILE"

# Enable SSL for the *next* server start (the real one) via postgresql.conf.
# Do NOT pass these as container command-line flags — see header comment.
cat >> "$PGDATA/postgresql.conf" <<EOF

# Added by 01-ssl.sh (ContextIQ local dev)
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
EOF
echo "[postgres-init] SSL enabled in postgresql.conf"
