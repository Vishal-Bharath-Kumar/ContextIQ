# Budget Limits Policy - Quick Reference

## At a Glance

**Purpose**: Control AI spending with automated budget enforcement  
**Version**: 1.0.0  
**Status**: ✅ Production Ready  
**Policy ID**: `contextiq.budget_limits`

---

## Limits

| Limit Type | Default Value | Override Available |
|------------|---------------|-------------------|
| Per-Request Max | $2.00 | ❌ No |
| Daily User Max | $10.00 | ✅ Admin/SRE Critical |
| Monthly User Max | $200.00 | ✅ Admin/SRE Critical |
| Monthly Department Max | $5,000.00 | ✅ Admin/SRE Critical |

---

## Decision Rules

```
✅ ALLOW if:
  - Request cost < $2.00
  - User daily spending + request < daily limit
  - User monthly spending + request < monthly limit
  - Dept monthly spending + request < dept limit

❌ DENY if:
  - Request cost > per-request limit
  - Would exceed daily user limit
  - Would exceed monthly user limit
  - Would exceed monthly dept budget

🚨 OVERRIDE if:
  - User role = Administrator OR SRE
  - Request priority = critical
```

---

## Denial Codes

| Code | Meaning | Action |
|------|---------|--------|
| `REQUEST_TOO_EXPENSIVE` | Single request > $2.00 | Reduce context or switch model |
| `DAILY_LIMIT_EXCEEDED` | Daily budget exhausted | Wait until next day (00:00 UTC) |
| `MONTHLY_LIMIT_EXCEEDED` | Monthly budget exhausted | Contact manager |
| `DEPARTMENT_BUDGET_EXCEEDED` | Dept budget exhausted | Contact dept manager |

---

## Warning Thresholds

| Threshold | Trigger | Action |
|-----------|---------|--------|
| 80% Daily | User at 80% of daily limit | Warning notification |
| 80% Monthly | User at 80% of monthly limit | Email alert |
| 80% Department | Dept at 80% of budget | Manager notification |

---

## API Quick Reference

### Check Budget Status
```bash
GET /api/v1/users/me/budget
Authorization: Bearer {token}
```

### Evaluate Policy
```bash
POST /api/v1/governance/evaluate
{
  "policy": "budget-limits",
  "input": { "user": {...}, "request": {...} }
}
```

### Get Policy Details
```bash
GET /api/v1/policies?name=budget-limits
```

---

## Dashboard Locations

- **User Budget**: Dashboard → My Budget
- **Department Budget**: Dashboard → Department Overview
- **Policy Status**: Admin Portal → Policies → Budget Limits
- **Violations**: Admin Portal → Governance → Violations

---

## Common Scenarios

### ✅ Normal Request
```
User spending: $2.50 / $10.00 daily
Request: $0.05
Result: ALLOWED
```

### ❌ Request Too Expensive
```
Request: $3.50
Limit: $2.00
Result: DENIED - REQUEST_TOO_EXPENSIVE
```

### ❌ Daily Limit Reached
```
User spending: $9.50 / $10.00
Request: $1.00
Result: DENIED - DAILY_LIMIT_EXCEEDED
```

### ✅ Emergency Override
```
Role: SRE
Priority: critical
Daily limit: exceeded
Result: ALLOWED (override)
```

---

## Emergency Contacts

| Issue | Contact |
|-------|---------|
| Increase Limits | Your Manager |
| Policy Issues | Platform Team |
| Budget Questions | Finance Team |
| Emergency Override | On-Call SRE |

---

## Key Files

| File | Purpose |
|------|---------|
| [policy.md](./budget-limits-policy.md) | Full documentation |
| [policy.rego](./budget-limits-policy.rego) | OPA implementation |
| [deployment.md](./budget-limits-deployment.md) | Setup guide |
| [examples.md](./budget-limits-examples.md) | Use cases |
| [tests.md](./budget-limits-test-cases.md) | Test scenarios |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-07-27 | Initial release |

---

## Support

🔗 **Docs**: [Full Policy Documentation](./budget-limits-policy.md)  
🐛 **Issues**: GitHub Issues  
📧 **Email**: platform-team@company.com  
💬 **Slack**: #platform-governance
