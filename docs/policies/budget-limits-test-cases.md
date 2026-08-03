# Budget Limits Policy - Test Cases

## Test Data Setup

### Test Users

```json
{
  "developer": {
    "id": "usr-001",
    "role": "Developer",
    "department": "Engineering",
    "email": "dev@example.com"
  },
  "sre": {
    "id": "usr-002",
    "role": "SRE",
    "department": "Operations",
    "email": "sre@example.com"
  },
  "admin": {
    "id": "usr-003",
    "role": "Administrator",
    "department": "Platform",
    "email": "admin@example.com"
  }
}
```

### Default Limits

```json
{
  "user_daily_max_usd": 10.0,
  "user_monthly_max_usd": 200.0,
  "department_monthly_max_usd": 5000.0,
  "request_max_usd": 2.0
}
```

## Test Cases

### TC-POL-001: Allow Request Within All Limits

**Description**: Normal request that passes all budget checks

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 0.05 },
  "current_spending": {
    "user_daily_usd": 2.0,
    "user_monthly_usd": 50.0,
    "department_monthly_usd": 1000.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: `allow = true`

---

### TC-POL-002: Deny Request - Per-Request Limit Exceeded

**Description**: Single request exceeds the per-request cost limit

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 3.0 },
  "current_spending": {
    "user_daily_usd": 0.0,
    "user_monthly_usd": 0.0,
    "department_monthly_usd": 0.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = false`
- `deny_reason = "REQUEST_TOO_EXPENSIVE"`

---

### TC-POL-003: Deny Request - Daily Limit Exceeded

**Description**: Request would push user over daily limit

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 0.5 },
  "current_spending": {
    "user_daily_usd": 9.8,
    "user_monthly_usd": 50.0,
    "department_monthly_usd": 1000.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = false`
- `deny_reason = "DAILY_LIMIT_EXCEEDED"`

---

### TC-POL-004: Deny Request - Monthly Limit Exceeded

**Description**: Request would push user over monthly limit

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 1.0 },
  "current_spending": {
    "user_daily_usd": 5.0,
    "user_monthly_usd": 199.5,
    "department_monthly_usd": 2000.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = false`
- `deny_reason = "MONTHLY_LIMIT_EXCEEDED"`

---

### TC-POL-005: Deny Request - Department Budget Exceeded

**Description**: Request would push department over budget

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 1.0 },
  "current_spending": {
    "user_daily_usd": 2.0,
    "user_monthly_usd": 50.0,
    "department_monthly_usd": 4999.5
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = false`
- `deny_reason = "DEPARTMENT_BUDGET_EXCEEDED"`

---

### TC-POL-006: Allow Request - Emergency Override (Admin)

**Description**: Administrator with critical priority bypasses limits

**Input**:
```json
{
  "user": { "id": "usr-003", "role": "Administrator", "department": "Platform" },
  "request": { 
    "estimated_cost_usd": 1.0,
    "priority": "critical"
  },
  "current_spending": {
    "user_daily_usd": 9.5,
    "user_monthly_usd": 199.5,
    "department_monthly_usd": 3000.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: `allow = true` (emergency override)

---

### TC-POL-007: Allow Request - Emergency Override (SRE)

**Description**: SRE with critical priority bypasses limits during incident

**Input**:
```json
{
  "user": { "id": "usr-002", "role": "SRE", "department": "Operations" },
  "request": { 
    "estimated_cost_usd": 1.0,
    "priority": "critical"
  },
  "current_spending": {
    "user_daily_usd": 9.8,
    "user_monthly_usd": 180.0,
    "department_monthly_usd": 2500.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: `allow = true` (emergency override)

---

### TC-POL-008: Warning - Approaching Daily Limit

**Description**: User at 80% of daily limit should trigger warning

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 0.1 },
  "current_spending": {
    "user_daily_usd": 8.0,
    "user_monthly_usd": 100.0,
    "department_monthly_usd": 2000.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = true`
- `warnings` contains `"APPROACHING_DAILY_LIMIT"`

---

### TC-POL-009: Warning - Approaching Monthly Limit

**Description**: User at 85% of monthly limit should trigger warning

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 0.5 },
  "current_spending": {
    "user_daily_usd": 5.0,
    "user_monthly_usd": 170.0,
    "department_monthly_usd": 2000.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = true`
- `warnings` contains `"APPROACHING_MONTHLY_LIMIT"`

---

### TC-POL-010: Warning - Approaching Department Budget

**Description**: Department at 82% of budget should trigger warning

**Input**:
```json
{
  "user": { "id": "usr-001", "role": "Developer", "department": "Engineering" },
  "request": { "estimated_cost_usd": 0.5 },
  "current_spending": {
    "user_daily_usd": 3.0,
    "user_monthly_usd": 80.0,
    "department_monthly_usd": 4100.0
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Expected**: 
- `allow = true`
- `warnings` contains `"APPROACHING_DEPARTMENT_BUDGET"`

---

## Running Tests

### Using OPA CLI

```bash
# Validate policy syntax
opa check budget-limits-policy.rego

# Test a specific case
opa eval -d budget-limits-policy.rego -i test-case-001.json "data.contextiq.budget_limits.allow"

# Run all test cases
opa test budget-limits-policy.rego budget-limits-tests.rego -v
```

### Integration Testing

Test cases should be executed against the live policy engine to verify:

1. Policy loads correctly in OPA
2. All test cases produce expected results
3. Performance meets SLA (< 10ms evaluation time)
4. Audit logs are generated correctly
5. Alerts trigger at appropriate thresholds
