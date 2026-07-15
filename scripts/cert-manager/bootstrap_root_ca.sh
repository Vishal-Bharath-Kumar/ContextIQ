#!/usr/bin/env bash
# scripts/cert-manager/bootstrap_root_ca.sh
#
# Creates the self-signed root CA certificate and stores it as a Kubernetes Secret.
# This Secret is referenced by the 'contextiq-internal-ca' ClusterIssuer.
#
# Run ONCE before deploying ClusterIssuers. Idempotent if Secret already exists.
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - openssl available on PATH
#   - contextiq-infra namespace must exist (created by TASK-US045-01)
set -euo pipefail

NAMESPACE="contextiq-infra"
SECRET_NAME="contextiq-root-ca"

if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "Root CA Secret $NAMESPACE/$SECRET_NAME already exists — skipping."
  exit 0
fi

echo "=== Generating ContextIQ root CA ==="

# Generate root CA key (4096-bit RSA) and self-signed cert (10-year validity for the CA itself)
openssl genrsa -out /tmp/contextiq-ca.key 4096
openssl req -new -x509 -days 3650 \
  -key /tmp/contextiq-ca.key \
  -out /tmp/contextiq-ca.crt \
  -subj "/CN=ContextIQ Internal CA/O=ContextIQ/OU=Platform Engineering"

# Store in Kubernetes Secret (tls type so cert-manager can consume tls.crt + tls.key)
kubectl create secret tls "$SECRET_NAME" \
  --cert=/tmp/contextiq-ca.crt \
  --key=/tmp/contextiq-ca.key \
  --namespace="$NAMESPACE"

# Wipe temp files — private key must not persist on disk
rm -f /tmp/contextiq-ca.key /tmp/contextiq-ca.crt

echo "=== Root CA Secret created in $NAMESPACE/$SECRET_NAME ==="
