# Budget Limits Policy - Usage Examples

## Overview

This document provides practical examples of how the Budget Limits Policy works in different scenarios.

## Example Scenarios

### Scenario 1: Normal Request - Allowed

**Context**: A developer makes a routine code completion request

**Request Details**:
- User: John Doe (Developer, Engineering)
- Model: Claude Sonnet
- Estimated Cost: $0.05
- Current Daily Spending: $2.50
- Current Monthly Spending: $45.00
- Department Monthly Spending: $1,200.00

**Policy Evaluation**:
```json
{
  "user": {
    "id": "john.doe@company.com",
    "role": "Developer",
    "department": "Engineering"
  },
  "request": {
    "id": "req-12345",
    "estimated_cost_usd": 0.05,
    "model": "claude-sonnet-4-5",
    "estimated_tokens": 1500
  },
  "current_spending": {
    "user_daily_usd": 2.50,
    "user_monthly_usd": 45.00,
    "department_monthly_usd": 1200.00
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 10000.0,
    "request_max_usd": 2.0
  }
}
```

**Policy Response**:
```json
{
  "allow": true,
  "deny_reason": "",
  "budget_status": {
    "remaining_daily": 7.45,
    "remaining_monthly": 154.95,
    "remaining_department": 8799.95,
    "warnings": []
  }
}
```

**Outcome**: ✅ Request proceeds

---

### Scenario 2: Expensive Request - Denied

**Context**: A user accidentally selects a very large context window

**Request Details**:
- User: Sarah Chen (Developer, Product)
- Model: GPT-4 Turbo
- Estimated Cost: $3.50
- Current Daily Spending: $1.20

**Policy Evaluation**:
```json
{
  "user": {
    "id": "sarah.chen@company.com",
    "role": "Developer",
    "department": "Product"
  },
  "request": {
    "id": "req-67890",
    "estimated_cost_usd": 3.50,
    "model": "gpt-4-turbo",
    "estimated_tokens": 500000
  },
  "current_spending": {
    "user_daily_usd": 1.20,
    "user_monthly_usd": 35.00,
    "department_monthly_usd": 800.00
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 200.0,
    "department_monthly_max_usd": 5000.0,
    "request_max_usd": 2.0
  }
}
```

**Policy Response**:
```json
{
  "allow": false,
  "deny_reason": "REQUEST_TOO_EXPENSIVE",
  "budget_status": {
    "remaining_daily": 8.80,
    "remaining_monthly": 165.00,
    "remaining_department": 4200.00,
    "warnings": []
  }
}
```

**User Message**:
> ⚠️ **Request Blocked: Cost Limit Exceeded**
> 
> This request would cost $3.50, which exceeds the per-request limit of $2.00.
> 
> **Suggestions:**
> - Reduce context window size
> - Select a more cost-effective model
> - Break request into smaller chunks
> 
> **Your Budget Status:**
> - Daily Remaining: $8.80
> - Monthly Remaining: $165.00

**Outcome**: ❌ Request blocked

---

### Scenario 3: Daily Limit Reached - Denied

**Context**: A user has been making many requests throughout the day

**Request Details**:
- User: Mike Johnson (Developer, Engineering)
- Estimated Cost: $1.00
- Current Daily Spending: $9.50

**Policy Response**:
```json
{
  "allow": false,
  "deny_reason": "DAILY_LIMIT_EXCEEDED",
  "budget_status": {
    "remaining_daily": 0.50,
    "remaining_monthly": 142.50,
    "remaining_department": 7500.00,
    "warnings": []
  }
}
```

**User Message**:
> ⚠️ **Request Blocked: Daily Budget Exceeded**
> 
> You've reached your daily spending limit of $10.00.
> 
> **Current Status:**
> - Today's Spending: $9.50
> - Remaining Today: $0.50
> - This Request: $1.00
> 
> **Options:**
> - Wait until tomorrow (resets at 00:00 UTC)
> - Contact your manager for a limit increase
> - Use a lower-cost model

**Outcome**: ❌ Request blocked until next day

---

### Scenario 4: Approaching Limit - Warning

**Context**: A user is nearing their monthly budget

**Request Details**:
- User: Emily Rodriguez (Developer, Data Science)
- Estimated Cost: $0.75
- Current Monthly Spending: $165.00 (82.5% of limit)

**Policy Response**:
```json
{
  "allow": true,
  "deny_reason": "",
  "budget_status": {
    "remaining_daily": 5.25,
    "remaining_monthly": 34.25,
    "remaining_department": 3200.00,
    "warnings": ["APPROACHING_MONTHLY_LIMIT"]
  }
}
```

**User Message**:
> ✅ **Request Approved**
> 
> ⚠️ **Budget Warning:** You're approaching your monthly spending limit.
> 
> **Budget Status:**
> - Monthly Spending: $165.75 / $200.00 (82.9%)
> - Remaining: $34.25
> - Days Until Reset: 5
> 
> Consider reviewing your usage patterns to stay within budget.

**Outcome**: ✅ Request proceeds with warning

---

### Scenario 5: Emergency Override - Allowed

**Context**: SRE investigating production incident

**Request Details**:
- User: Alex Kim (SRE, Operations)
- Priority: CRITICAL
- Estimated Cost: $1.50
- Current Daily Spending: $9.00 (would exceed limit)

**Policy Evaluation**:
```json
{
  "user": {
    "id": "alex.kim@company.com",
    "role": "SRE",
    "department": "Operations"
  },
  "request": {
    "id": "req-incident-999",
    "estimated_cost_usd": 1.50,
    "model": "claude-opus-4",
    "priority": "critical"
  },
  "current_spending": {
    "user_daily_usd": 9.00,
    "user_monthly_usd": 380.00,
    "department_monthly_usd": 7200.00
  },
  "limits": {
    "user_daily_max_usd": 10.0,
    "user_monthly_max_usd": 400.0,
    "department_monthly_max_usd": 8000.0,
    "request_max_usd": 2.0
  }
}
```

**Policy Response**:
```json
{
  "allow": true,
  "deny_reason": "",
  "budget_status": {
    "remaining_daily": -0.50,
    "remaining_monthly": 18.50,
    "remaining_department": 798.50,
    "warnings": ["APPROACHING_MONTHLY_LIMIT", "APPROACHING_DEPARTMENT_BUDGET"]
  }
}
```

**Audit Log Entry**:
```json
{
  "timestamp": "2026-07-27T14:35:22Z",
  "event": "EMERGENCY_OVERRIDE_USED",
  "user_id": "alex.kim@company.com",
  "role": "SRE",
  "request_id": "req-incident-999",
  "priority": "critical",
  "exceeded_limit": "daily",
  "cost_usd": 1.50,
  "reason": "Production incident investigation"
}
```

**Outcome**: ✅ Request proceeds (emergency override)

---

### Scenario 6: Department Budget Exceeded

**Context**: Department has exhausted monthly AI budget

**Request Details**:
- User: Tom Wilson (Developer, Marketing)
- Department Monthly Spending: $4,995.00
- Request Cost: $10.00

**Policy Response**:
```json
{
  "allow": false,
  "deny_reason": "DEPARTMENT_BUDGET_EXCEEDED",
  "budget_status": {
    "remaining_daily": 7.50,
    "remaining_monthly": 155.00,
    "remaining_department": 5.00,
    "warnings": ["APPROACHING_DEPARTMENT_BUDGET"]
  }
}
```

**User Message**:
> ⚠️ **Request Blocked: Department Budget Exceeded**
> 
> The Marketing department has reached its monthly AI budget limit.
> 
> **Department Status:**
> - Monthly Budget: $5,000.00
> - Current Spending: $4,995.00
> - Remaining: $5.00
> - Your Request: $10.00
> 
> **Next Steps:**
> - Contact your department manager
> - Request budget increase for next month
> - Prioritize critical AI usage

**Outcome**: ❌ Request blocked (department budget)

---

## Admin Dashboard Views

### User Budget Overview

```
┌─────────────────────────────────────────────────────────────┐
│ User: john.doe@company.com (Developer, Engineering)        │
├─────────────────────────────────────────────────────────────┤
│ Daily Budget:   $2.50 / $10.00  [████████░░] 25%          │
│ Monthly Budget: $45.00 / $200.00 [████░░░░░░] 22.5%       │
│                                                             │
│ Recent Requests: 23 today, 156 this month                  │
│ Avg Cost/Request: $0.29                                    │
│ Most Used Model: claude-sonnet-4-5 (75%)                   │
└─────────────────────────────────────────────────────────────┘
```

### Department Budget Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Department: Engineering                                     │
├─────────────────────────────────────────────────────────────┤
│ Monthly Budget: $1,200 / $10,000 [████░░░░░░] 12%         │
│                                                             │
│ Top Users:                                                  │
│   1. john.doe@company.com      $45.00                      │
│   2. sarah.smith@company.com   $38.50                      │
│   3. mike.jones@company.com    $32.75                      │
│                                                             │
│ Trend: ↗ +15% vs. last month                               │
│ Projected End-of-Month: $3,200 (32% of budget)            │
└─────────────────────────────────────────────────────────────┘
```

## API Examples

### Check Budget Before Request

```bash
curl -X POST http://localhost:8080/api/v1/governance/evaluate \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "policy": "budget-limits",
    "input": {
      "user": {
        "id": "user-123",
        "role": "Developer",
        "department": "Engineering"
      },
      "request": {
        "estimated_cost_usd": 0.5
      }
    }
  }'
```

### Get User Budget Status

```bash
curl -X GET http://localhost:8080/api/v1/users/me/budget \
  -H "Authorization: Bearer ${TOKEN}"
```

Response:
```json
{
  "daily": {
    "limit": 10.0,
    "spent": 2.50,
    "remaining": 7.50,
    "percentage_used": 25.0
  },
  "monthly": {
    "limit": 200.0,
    "spent": 45.00,
    "remaining": 155.00,
    "percentage_used": 22.5
  },
  "department": {
    "limit": 10000.0,
    "spent": 1200.00,
    "remaining": 8800.00,
    "percentage_used": 12.0
  }
}
```

## Best Practices

1. **Monitor Your Budget**: Check your budget status regularly in the dashboard
2. **Optimize Requests**: Use appropriate models for the task complexity
3. **Batch Operations**: Group related requests to minimize overhead
4. **Use Caching**: Leverage cached results when possible
5. **Review Patterns**: Analyze usage patterns to optimize spending
6. **Plan Ahead**: Request budget increases before running out
7. **Emergency Contacts**: Know who to contact for urgent overrides
