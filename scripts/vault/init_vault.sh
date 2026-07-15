#!/usr/bin/env bash
# scripts/vault/init_vault.sh
# One-time Vault initialization and Kubernetes auth configuration.
#
# Prerequisites:
#   - Vault pods are Running (but sealed/uninitialized)
#   - kubectl access to contextiq-security namespace
#   - vault CLI installed locally
#
# SECURITY: The root token and unseal keys are printed to stdout and must be
# saved to a secure offline location immediately. They are NOT stored anywhere
# by this script. Delete /tmp/vault-init.json after saving the keys.
set -euo pipefail

NAMESPACE="contextiq-security"
VAULT_POD="vault-0"
INIT_OUTPUT="/tmp/vault-init.json"

echo "=== Port-forwarding to $VAULT_POD ==="
kubectl port-forward -n "$NAMESPACE" "$VAULT_POD" 8200:8200 &
PF_PID=$!
# Ensure port-forward is cleaned up on exit regardless of success/failure
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT
sleep 3

export VAULT_ADDR="https://127.0.0.1:8200"
export VAULT_SKIP_VERIFY="true"   # skip TLS verify for local port-forward tunnel only

echo "=== Waiting for Vault to be reachable ==="
for i in {1..10}; do
  vault status -tls-skip-verify > /dev/null 2>&1 && break || true
  echo "  Attempt $i/10 — retrying in 3s..."
  sleep 3
done

echo "=== Initialising Vault (5 key shares, threshold 3) ==="
vault operator init \
  -key-shares=5 \
  -key-threshold=3 \
  -format=json | tee "$INIT_OUTPUT"

echo ""
echo "================================================================"
echo "IMPORTANT: Save $INIT_OUTPUT to a secure offline location NOW."
echo "This file contains the root token and all unseal keys."
echo "Delete it from disk after saving."
echo "================================================================"
echo ""

# Extract root token for subsequent bootstrap steps
ROOT_TOKEN=$(jq -r '.root_token' "$INIT_OUTPUT")
export VAULT_TOKEN="$ROOT_TOKEN"

echo "=== Enabling Kubernetes auth method ==="
vault auth enable kubernetes

echo "=== Configuring Kubernetes auth ==="
# Vault reads the K8s API server CA and service account JWT from the pod's
# projected volume. These values are safe to read from the running pod.
KUBE_HOST="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"
SA_JWT=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
CA_CERT=$(cat /var/run/secrets/kubernetes.io/serviceaccount/ca.crt)

vault write auth/kubernetes/config \
  kubernetes_host="$KUBE_HOST" \
  token_reviewer_jwt="$SA_JWT" \
  kubernetes_ca_cert="$CA_CERT" \
  issuer="https://kubernetes.default.svc.cluster.local"

echo ""
echo "=== Vault initialisation complete ==="
echo "Root token is available in VAULT_TOKEN env var for subsequent setup scripts."
echo "Run secrets engine and policy setup scripts next."
