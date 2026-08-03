# Budget Limits Policy

## Overview

The Budget Limits Policy enforces spending controls for AI model usage across the ContextIQ platform. This policy prevents cost overruns by setting per-user, per-department, and per-request limits based on organizational rules.

## Policy Objectives

1. **Cost Control**: Prevent unexpected AI spending spikes
2. **Fair Resource Allocation**: Ensure equitable distribution of AI resources
3. **Budget Compliance**: Enforce departmental budget constraints
4. **Anomaly Detection**: Flag unusual spending patterns

## Policy Categories

### User-Level Limits

- **Daily Spending Cap**: Maximum cost per user per day
- **Monthly Spending Cap**: Maximum cost per user per month
- **Per-Request Limit**: Maximum cost for a single AI request

### Department-Level Limits

- **Monthly Budget**: Total departmental spending limit
- **Reserve Threshold**: Percentage of budget to keep in reserve

### Role-Based Limits

- **Developer**: Standard limits for development activities
- **SRE**: Extended limits for incident response
- **Administrator**: Higher limits for platform management
- **Auditor**: Read-only access with minimal cost

## Policy Input Schema

The policy expects the following input structure:

```json
{
  "user": {
    "id": "string",
    "role": "string",
    "department": "string",
    "email": "string"
  },
  "request": {
    "id": "string",
    "estimated_cost_usd": "number",
    "model": "string",
    "estimated_tokens": "number"
  },
  "current_spending": {
    "user_daily_usd": "number",
    "user_monthly_usd": "number",
    "department_monthly_usd": "number"
  },
  "limits": {
    "user_daily_max_usd": "number",
    "user_monthly_max_usd": "number",
    "department_monthly_max_usd": "number",
    "request_max_usd": "number"
  }
}
```

## Policy Rules

### 1. Per-Request Cost Limit

Reject requests that exceed the maximum cost per request threshold.

**Rationale**: Prevents accidental invocation of expensive models with large context windows.

### 2. Daily User Budget

Track and enforce daily spending limits per user.

**Rationale**: Prevents a single user from consuming excessive resources in a short time period.

### 3. Monthly User Budget

Enforce monthly spending caps per user.

**Rationale**: Ensures long-term cost predictability and fair resource distribution.

### 4. Department Budget

Enforce departmental monthly budgets with reserve requirements.

**Rationale**: Aligns AI spending with organizational budget allocations.

### 5. Role-Based Overrides

Allow administrators and SREs to exceed normal limits during critical operations.

**Rationale**: Ensures platform reliability and incident response capabilities.

## Policy Outcomes

### Allow

Request is permitted and will proceed with AI model invocation.

### Deny

Request is blocked with a specific reason code:

- `DAILY_LIMIT_EXCEEDED`: User has exceeded daily spending limit
- `MONTHLY_LIMIT_EXCEEDED`: User has exceeded monthly spending limit
- `DEPARTMENT_BUDGET_EXCEEDED`: Department has exceeded monthly budget
- `REQUEST_TOO_EXPENSIVE`: Single request cost exceeds threshold
- `BUDGET_RESERVE_REACHED`: Department budget reserve threshold reached

## Implementation

See `budget-limits-policy.rego` for the Open Policy Agent implementation.

## Monitoring & Alerts

### Alert Triggers

1. User approaches 80% of daily limit
2. User approaches 90% of monthly limit
3. Department approaches 80% of monthly budget
4. Any request denied due to budget constraints

### Audit Trail

All budget policy decisions are logged to the policy audit log with:

- User ID and role
- Request ID and estimated cost
- Current spending levels
- Denial reason (if applicable)
- Timestamp

## Configuration

Policy limits are configured in the OPA data layer and can be customized per:

- Organization
- Department
- User role
- Time period (business hours vs. off-hours)

## Related Policies

- Model Selection Policy
- Cost Optimization Policy
- Resource Allocation Policy
- Emergency Override Policy
