#!/usr/bin/env bash
# scripts/ci/promote_to_production.sh
# Standalone production promotion script.
#
# Performs the same steps as the promote-to-production CI job but can be
# run manually (e.g. for hotfix promotions or local testing).
#
# Prerequisites:
#   - argocd CLI installed and logged in (or ARGOCD_SERVER / ARGOCD_AUTH_TOKEN set)
#   - yq v4 installed
#   - Git remote writable via the current credential
#   - GITOPS_DEPLOY_KEY or equivalent git auth configured
#
# Usage:
#   promote_to_production.sh <git-sha>
set -euo pipefail

GIT_SHA="${1:?Usage: $0 <git-sha>}"
PRODUCTION_APP="${PRODUCTION_APP:-contextiq-production}"
VALUES_FILE="helm/contextiq/values-production.yaml"
ARGOCD_OPTS="${ARGOCD_OPTS:---grpc-web}"

echo "=== ContextIQ Production Promotion ==="
echo "  SHA:          $GIT_SHA"
echo "  ArgoCD app:   $PRODUCTION_APP"
echo "  Values file:  $VALUES_FILE"
echo ""

# Step 1: Update production image tags
echo "--- Step 1: updating image tags ---"
bash scripts/ci/update_image_tags.sh "$GIT_SHA" "$VALUES_FILE"

# Step 2: Commit and push
echo "--- Step 2: committing image tag update ---"
git config user.name  "promotion-bot"
git config user.email "promotion-bot@contextiq.io"
git add "$VALUES_FILE"
if git diff --staged --quiet; then
  echo "No changes to commit — SHA $GIT_SHA is already deployed to production."
else
  git commit -m "ci: promote $GIT_SHA to production [skip ci]"
  git push origin main
  echo "Committed and pushed."
fi

# Step 3: Hard refresh + wait for sync
echo "--- Step 3: triggering ArgoCD hard refresh ---"
argocd app get "$PRODUCTION_APP" --hard-refresh

echo "--- Step 4: waiting for production sync (max 9 min) ---"
DEADLINE=$(( $(date +%s) + 540 ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  APP_JSON=$(argocd app get "$PRODUCTION_APP" --output json 2>/dev/null || echo '{}')
  STATUS=$(printf '%s' "$APP_JSON" \
    | jq -r '"\(.status.sync.status // "Unknown")/\(.status.health.status // "Unknown")"')
  REMAINING=$(( DEADLINE - $(date +%s) ))
  echo "  Status: $STATUS  remaining: ${REMAINING}s"
  if [ "$STATUS" = "Synced/Healthy" ]; then
    echo ""
    echo "SUCCESS: $PRODUCTION_APP is Synced and Healthy."
    exit 0
  fi
  sleep 15
done

echo ""
echo "ERROR: $PRODUCTION_APP did not reach Synced/Healthy within 9 minutes." >&2
argocd app get "$PRODUCTION_APP" --output json \
  | jq '{sync: .status.sync.status, health: .status.health.status, conditions: .status.conditions}'
exit 1
