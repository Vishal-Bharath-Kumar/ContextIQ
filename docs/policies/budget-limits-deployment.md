# Budget Limits Policy - Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying the Budget Limits Policy to your ContextIQ instance.

## Prerequisites

1. Administrator access to the ContextIQ Admin Portal
2. OPA service running and accessible
3. Database migrations completed (policy_definitions table exists)

## Deployment Steps

### Step 1: Create the Policy via API

Use the Admin Portal or API to create the policy:

```bash
curl -X POST http://localhost:8080/api/v1/policies \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d @budget-limits-policy-create.json
```

**budget-limits-policy-create.json**:
```json
{
  "name": "budget-limits",
  "version": "1.0.0",
  "description": "Enforce spending controls for AI model usage with per-user, per-department, and per-request limits",
  "rego_body": "package contextiq.budget_limits\n\n# Budget Limits Policy\n# Version: 1.0.0\n\nimport rego.v1\n\ndefault allow := false\ndefault deny_reason := \"\"\n\nallow if {\n    not request_too_expensive\n    not daily_limit_exceeded\n    not monthly_limit_exceeded\n    not department_budget_exceeded\n}\n\nrequest_too_expensive if {\n    input.request.estimated_cost_usd > input.limits.request_max_usd\n}\n\ndaily_limit_exceeded if {\n    input.current_spending.user_daily_usd + input.request.estimated_cost_usd > input.limits.user_daily_max_usd\n    not has_emergency_override\n}\n\nmonthly_limit_exceeded if {\n    input.current_spending.user_monthly_usd + input.request.estimated_cost_usd > input.limits.user_monthly_max_usd\n    not has_emergency_override\n}\n\ndepartment_budget_exceeded if {\n    input.current_spending.department_monthly_usd + input.request.estimated_cost_usd > input.limits.department_monthly_max_usd\n    not has_emergency_override\n}\n\nhas_emergency_override if {\n    input.user.role in [\"Administrator\", \"SRE\"]\n    input.request.priority == \"critical\"\n}\n\ndeny_reason := reason if {\n    request_too_expensive\n    reason := \"REQUEST_TOO_EXPENSIVE\"\n} else := reason if {\n    daily_limit_exceeded\n    reason := \"DAILY_LIMIT_EXCEEDED\"\n} else := reason if {\n    monthly_limit_exceeded\n    reason := \"MONTHLY_LIMIT_EXCEEDED\"\n} else := reason if {\n    department_budget_exceeded\n    reason := \"DEPARTMENT_BUDGET_EXCEEDED\"\n}\n\nremaining_daily_budget := budget if {\n    budget := input.limits.user_daily_max_usd - input.current_spending.user_daily_usd\n}\n\nremaining_monthly_budget := budget if {\n    budget := input.limits.user_monthly_max_usd - input.current_spending.user_monthly_usd\n}\n\nremaining_department_budget := budget if {\n    budget := input.limits.department_monthly_max_usd - input.current_spending.department_monthly_usd\n}\n\nwarn_daily_limit := true if {\n    threshold := input.limits.user_daily_max_usd * 0.8\n    input.current_spending.user_daily_usd >= threshold\n}\n\nwarn_monthly_limit := true if {\n    threshold := input.limits.user_monthly_max_usd * 0.8\n    input.current_spending.user_monthly_usd >= threshold\n}\n\nwarn_department_budget := true if {\n    threshold := input.limits.department_monthly_max_usd * 0.8\n    input.current_spending.department_monthly_usd >= threshold\n}\n\nresponse := {\n    \"allow\": allow,\n    \"deny_reason\": deny_reason,\n    \"budget_status\": {\n        \"remaining_daily\": remaining_daily_budget,\n        \"remaining_monthly\": remaining_monthly_budget,\n        \"remaining_department\": remaining_department_budget,\n        \"warnings\": warnings\n    }\n}\n\nwarnings := w if {\n    w := array.concat(\n        array.concat(\n            [warning | warn_daily_limit; warning := \"APPROACHING_DAILY_LIMIT\"],\n            [warning | warn_monthly_limit; warning := \"APPROACHING_MONTHLY_LIMIT\"]\n        ),\n        [warning | warn_department_budget; warning := \"APPROACHING_DEPARTMENT_BUDGET\"]\n    )\n}"
}
```

### Step 2: Validate the Policy

Before activation, validate the policy syntax:

```bash
curl -X POST http://localhost:8080/api/v1/policies/validate \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"rego_body": "<rego_content>"}'
```

Expected response:
```json
{
  "valid": true,
  "errors": []
}
```

### Step 3: Preview Policy Impact

Test the policy against recent execution traces:

```bash
curl -X POST http://localhost:8080/api/v1/policies/${POLICY_ID}/preview \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

This will show how many requests would have been blocked if this policy were active.

### Step 4: Activate the Policy

Once validated and previewed, activate the policy:

```bash
curl -X POST http://localhost:8080/api/v1/policies/${POLICY_ID}/activate \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

Expected response:
```json
{
  "id": "uuid",
  "policy_group": "budget-limits",
  "version": "1.0.0",
  "status": "active",
  "activated_at": "2026-07-27T10:30:00Z"
}
```

## Configuration

### Setting Budget Limits

Configure budget limits in OPA data layer:

```bash
# Create budget configuration
curl -X PUT http://localhost:8181/v1/data/contextiq/config/budget_limits \
  -H "Content-Type: application/json" \
  -d @budget-config.json
```

**budget-config.json**:
```json
{
  "default_limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  },
  "role_overrides": {
    "SRE": {
      "user_daily_max_usd": 20.0,
      "user_monthly_max_usd": 400.0
    },
    "Administrator": {
      "user_daily_max_usd": 50.0,
      "user_monthly_max_usd": 1000.0
    }
  },
  "department_budgets": {
    "Engineering": {
      "department_monthly_max_usd": 10000.0
    },
    "Operations": {
      "department_monthly_max_usd": 8000.0
    },
    "Platform": {
      "department_monthly_max_usd": 15000.0
    }
  }
}
```

## Integration Points

### Governance Agent Integration

The Governance Agent will automatically evaluate this policy before model invocation:

1. Calculate estimated request cost
2. Fetch current user and department spending
3. Evaluate budget limits policy
4. Allow or deny request based on policy decision

### Cost Tracking Service

The policy relies on the Cost Tracking Service to provide:

- Real-time spending data per user
- Aggregated department spending
- Historical cost trends

Ensure the Cost Tracking Service is running and configured.

## Monitoring & Alerts

### Setting Up Alerts

Configure alerts for budget violations:

```yaml
# prometheus-alerts.yml
groups:
  - name: budget_limits
    rules:
      - alert: UserApproachingDailyLimit
        expr: user_daily_spending_usd / user_daily_limit_usd > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "User {{ $labels.user_id }} approaching daily budget limit"
          
      - alert: DepartmentApproachingMonthlyBudget
        expr: department_monthly_spending_usd / department_monthly_limit_usd > 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Department {{ $labels.department }} approaching monthly budget"
          
      - alert: BudgetPolicyDeniedRequest
        expr: rate(budget_policy_denied_total[5m]) > 0
        labels:
          severity: info
        annotations:
          summary: "Budget policy denied request for user {{ $labels.user_id }}"
```

### Dashboard Metrics

Add budget metrics to Grafana dashboards:

- Total spending by user (daily/monthly)
- Total spending by department (monthly)
- Budget utilization percentage
- Policy denial rate
- Cost per request trend

## Rollback Plan

If the policy causes issues, deactivate it:

```bash
curl -X POST http://localhost:8080/api/v1/policies/${POLICY_ID}/deactivate \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

Or rollback to a previous version:

```bash
curl -X POST http://localhost:8080/api/v1/policies/${PREVIOUS_VERSION_ID}/activate \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

## Troubleshooting

### Policy Not Enforcing

1. Verify policy status: `GET /v1/policies/${POLICY_ID}`
2. Check OPA service: `curl http://localhost:8181/health`
3. Review audit logs: `GET /v1/policies/${POLICY_ID}/audit`
4. Verify cost tracking service is running

### Incorrect Budget Calculations

1. Check OPA data configuration
2. Verify cost estimation accuracy
3. Review spending aggregation logic
4. Check timezone handling for daily resets

### Emergency Override Not Working

1. Verify user role in JWT claims
2. Check request priority field
3. Review emergency override logic in policy
4. Verify `has_emergency_override` rule evaluation

## Support

For issues or questions:

- Review policy audit trail: Admin Portal → Policies → Budget Limits → Audit Trail
- Check logs: `docker compose logs governance`
- Open an issue in the ContextIQ repository
