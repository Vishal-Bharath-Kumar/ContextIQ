.PHONY: validate-staging validate-prod healthz-staging healthz-prod \
        rollout-staging rollout-prod netpol-staging validate-hpa-staging

# ──────────────────────────────────────────────────────────────────────────────
# Full validation suites
# ──────────────────────────────────────────────────────────────────────────────

validate-staging: ## Run full validation suite against staging cluster
	@echo "--- Rollout status ---"
	KUBECONFIG=~/.kube/staging bash scripts/validate/rollout_status.sh
	@echo "--- Healthz checks ---"
	KUBECONFIG=~/.kube/staging python scripts/validate/healthz_check.py --env staging
	@echo "--- Network policy checks ---"
	KUBECONFIG=~/.kube/staging bash scripts/validate/network_policy_check.sh
	@echo "--- Cluster state assertions ---"
	KUBECONFIG=~/.kube/staging pytest tests/infra/ -v

validate-prod: ## Run full validation suite against production cluster
	@echo "--- Rollout status ---"
	KUBECONFIG=~/.kube/prod bash scripts/validate/rollout_status.sh
	@echo "--- Healthz checks ---"
	KUBECONFIG=~/.kube/prod python scripts/validate/healthz_check.py --env prod
	@echo "--- Cluster state assertions ---"
	KUBECONFIG=~/.kube/prod pytest tests/infra/ -v

# ──────────────────────────────────────────────────────────────────────────────
# Individual targets (useful in CI pipeline steps)
# ──────────────────────────────────────────────────────────────────────────────

rollout-staging: ## Poll rollout status for all contextiq-* workloads in staging
	KUBECONFIG=~/.kube/staging bash scripts/validate/rollout_status.sh

rollout-prod: ## Poll rollout status for all contextiq-* workloads in production
	KUBECONFIG=~/.kube/prod bash scripts/validate/rollout_status.sh

healthz-staging: ## Probe /healthz on all services in staging
	python scripts/validate/healthz_check.py --env staging

healthz-prod: ## Probe /healthz on all services in production
	python scripts/validate/healthz_check.py --env prod

netpol-staging: ## Spot-check network policy allow/deny matrix in staging
	KUBECONFIG=~/.kube/staging bash scripts/validate/network_policy_check.sh

validate-hpa-staging: ## Run HPA validation suite in staging (AC-4, AC-5, AC-6)
	@echo "--- HPA spec assertions ---"
	KUBECONFIG=~/.kube/staging pytest tests/infra/test_hpa_config.py -v
	@echo "--- Starting load generator, then checking scale-up timing ---"
	KUBECONFIG=~/.kube/staging python scripts/validate/hpa_load_generator.py \
	    --target http://mcp-gateway.contextiq-gateway.svc.cluster.local \
	    --concurrency 60 \
	    --duration 90 & \
	LOAD_PID=$$!; \
	sleep 10; \
	echo "--- Scale-up timing check (agent-worker) ---"; \
	KUBECONFIG=~/.kube/staging python scripts/validate/hpa_timing_check.py \
	    --namespace contextiq-agents \
	    --hpa-name release-name-agent-worker \
	    --expected-min-replicas 4 \
	    --scale-up-deadline 30 \
	    --scale-down-hold 60; \
	wait $$LOAD_PID || true
	@echo "--- PDB disruption test ---"
	KUBECONFIG=~/.kube/staging bash scripts/validate/pdb_disruption_test.sh
	@echo "=== HPA validation complete ==="

# ──────────────────────────────────────────────────────────────────────────────
# Helm lint — verify all service charts before apply
# ──────────────────────────────────────────────────────────────────────────────

lint: ## helm lint all service charts
	helm lint helm/charts/mcp-gateway/
	helm lint helm/charts/agent-worker/
	helm lint helm/charts/admin-portal/
	helm lint helm/charts/keycloak/
	helm lint helm/charts/jaeger/
	helm lint helm/charts/indexing-service/

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
