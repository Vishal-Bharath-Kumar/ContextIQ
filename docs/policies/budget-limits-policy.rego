package contextiq.budget_limits

# Budget Limits Policy
# Version: 1.0.0
# Purpose: Enforce spending controls for AI model usage across the platform

import rego.v1

# Default deny - requires explicit allow
default allow := false
default deny_reason := ""

# Allow the request if all budget checks pass
allow if {
    not request_too_expensive
    not daily_limit_exceeded
    not monthly_limit_exceeded
    not department_budget_exceeded
}

# Check if the single request cost exceeds the per-request limit
request_too_expensive if {
    input.request.estimated_cost_usd > input.limits.request_max_usd
}

# Check if user has exceeded their daily spending limit
daily_limit_exceeded if {
    input.current_spending.user_daily_usd + input.request.estimated_cost_usd > input.limits.user_daily_max_usd
    not has_emergency_override
}

# Check if user has exceeded their monthly spending limit
monthly_limit_exceeded if {
    input.current_spending.user_monthly_usd + input.request.estimated_cost_usd > input.limits.user_monthly_max_usd
    not has_emergency_override
}

# Check if department has exceeded its monthly budget
department_budget_exceeded if {
    input.current_spending.department_monthly_usd + input.request.estimated_cost_usd > input.limits.department_monthly_max_usd
    not has_emergency_override
}

# Emergency override for administrators and SREs during critical operations
has_emergency_override if {
    input.user.role in ["Administrator", "SRE"]
    input.request.priority == "critical"
}

# Determine the specific denial reason
deny_reason := reason if {
    request_too_expensive
    reason := "REQUEST_TOO_EXPENSIVE"
} else := reason if {
    daily_limit_exceeded
    reason := "DAILY_LIMIT_EXCEEDED"
} else := reason if {
    monthly_limit_exceeded
    reason := "MONTHLY_LIMIT_EXCEEDED"
} else := reason if {
    department_budget_exceeded
    reason := "DEPARTMENT_BUDGET_EXCEEDED"
}

# Calculate remaining budget for the user (daily)
remaining_daily_budget := budget if {
    budget := input.limits.user_daily_max_usd - input.current_spending.user_daily_usd
}

# Calculate remaining budget for the user (monthly)
remaining_monthly_budget := budget if {
    budget := input.limits.user_monthly_max_usd - input.current_spending.user_monthly_usd
}

# Calculate remaining department budget
remaining_department_budget := budget if {
    budget := input.limits.department_monthly_max_usd - input.current_spending.department_monthly_usd
}

# Warning threshold: user approaching daily limit (80%)
warn_daily_limit := true if {
    threshold := input.limits.user_daily_max_usd * 0.8
    input.current_spending.user_daily_usd >= threshold
}

# Warning threshold: user approaching monthly limit (80%)
warn_monthly_limit := true if {
    threshold := input.limits.user_monthly_max_usd * 0.8
    input.current_spending.user_monthly_usd >= threshold
}

# Warning threshold: department approaching budget limit (80%)
warn_department_budget := true if {
    threshold := input.limits.department_monthly_max_usd * 0.8
    input.current_spending.department_monthly_usd >= threshold
}

# Build a comprehensive response with budget status
response := {
    "allow": allow,
    "deny_reason": deny_reason,
    "budget_status": {
        "remaining_daily": remaining_daily_budget,
        "remaining_monthly": remaining_monthly_budget,
        "remaining_department": remaining_department_budget,
        "warnings": warnings
    }
}

# Collect all active warnings
warnings := w if {
    w := array.concat(
        array.concat(
            [warning | warn_daily_limit; warning := "APPROACHING_DAILY_LIMIT"],
            [warning | warn_monthly_limit; warning := "APPROACHING_MONTHLY_LIMIT"]
        ),
        [warning | warn_department_budget; warning := "APPROACHING_DEPARTMENT_BUDGET"]
    )
}
