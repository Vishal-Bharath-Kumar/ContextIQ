#!/usr/bin/env bash
# scripts/ci/update_image_tags.sh
# Updates the .image.tag fields in a Helm values file to the new git SHA.
#
# Usage:
#   update_image_tags.sh <git-sha> <values-file>
#
# Arguments:
#   git-sha      — the full git SHA to write into each service's image.tag
#   values-file  — path to the Helm values YAML file to update in-place
#
# BUG FIX: the spec declared a third $REGISTRY argument that was accepted but
# never used inside the script body.  Removed to keep the interface honest.
#
# BUG FIX: the spec used ${SVC//-/_} to convert service names to snake_case
# (e.g. mcp-gateway → mcp_gateway) as a workaround for yq's treatment of
# hyphens.  This produces the WRONG yq path because the actual Helm values
# file uses hyphenated keys (mcp-gateway, agent-worker).  Fixed by quoting
# the key name in the yq path expression: .\"mcp-gateway\".image.tag
#
# BUG FIX: admin-api in spec does not exist — the chart key is admin-portal.
#
# Requires: yq v4 (mikefarah/yq) — installed by the CI workflow step
set -euo pipefail

NEW_SHA="${1:?Usage: $0 <git-sha> <values-file>}"
VALUES_FILE="${2:?Usage: $0 <git-sha> <values-file>}"

if [[ ! -f "$VALUES_FILE" ]]; then
  echo "ERROR: values file not found: $VALUES_FILE" >&2
  exit 1
fi

echo "=== Updating image tags in $VALUES_FILE to $NEW_SHA ==="

# Service keys exactly as they appear in the Helm values YAML (hyphenated).
# BUG FIX: was (mcp-gateway agent-worker indexing-service admin-api) in spec;
# admin-api does not exist — the correct key is admin-portal.
SERVICES=(mcp-gateway agent-worker indexing-service admin-portal)

for SVC in "${SERVICES[@]}"; do
  # BUG FIX: quote the YAML key in the yq path so hyphens are treated as part
  # of the key name, not as arithmetic.  Without quotes, yq parses
  # .mcp-gateway as (.mcp) - (gateway), which silently produces no match.
  YQ_PATH=".\"${SVC}\".image.tag"

  # Verify the key exists before updating to avoid silently creating new nodes
  CURRENT=$(yq e "${YQ_PATH}" "$VALUES_FILE" 2>/dev/null || true)
  if [[ -z "$CURRENT" || "$CURRENT" == "null" ]]; then
    echo "  WARNING: ${YQ_PATH} not found in $VALUES_FILE — skipping"
    continue
  fi

  yq e "${YQ_PATH} = \"${NEW_SHA}\"" -i "$VALUES_FILE"
  echo "  Updated ${YQ_PATH} → ${NEW_SHA}"
done

echo "=== Image tag update complete ==="
echo "--- $VALUES_FILE ---"
cat "$VALUES_FILE"
