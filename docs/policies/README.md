# ContextIQ Governance Policies

This directory contains policy definitions, documentation, and deployment guides for the ContextIQ governance engine.

## Overview

ContextIQ uses [Open Policy Agent (OPA)](https://www.openpolicyagent.org/) to enforce governance policies across the platform. Policies are written in [Rego](https://www.openpolicyagent.org/docs/latest/policy-language/), OPA's declarative policy language.

## Available Policies

### Budget Limits Policy

**Purpose**: Enforce spending controls for AI model usage with per-user, per-department, and per-request limits.

**Files**:
- [`budget-limits-policy.md`](./budget-limits-policy.md) - Policy documentation
- [`budget-limits-policy.rego`](./budget-limits-policy.rego) - OPA/Rego implementation
- [`budget-limits-test-cases.md`](./budget-limits-test-cases.md) - Test scenarios
- [`budget-limits-deployment.md`](./budget-limits-deployment.md) - Deployment guide
- [`budget-limits-examples.md`](./budget-limits-examples.md) - Usage examples

**Key Features**:
- Per-request cost limits
- Daily user spending limits
- Monthly user spending limits
- Department budget enforcement
- Emergency override for critical operations
- Budget warning thresholds

**Policy Category**: Cost Control

**Status**: ✅ Ready for deployment

---

## Policy Categories

ContextIQ supports the following policy categories as defined in the [Business Requirements Document](../BRD.md):

1. **Access Policies** - Control user access to knowledge sources
2. **Model Policies** - Restrict which LLMs can be used by department/role
3. **Connector Policies** - Control access to enterprise connectors
4. **Cost Policies** - Limit AI spending (✅ Budget Limits Policy)
5. **Compliance Policies** - Enforce regulatory requirements (GDPR, HIPAA, etc.)

## Policy Lifecycle

```
Create → Validate → Preview → Activate → Monitor → Update/Rollback
```

### 1. Create

Author a new policy using Rego syntax or use the Admin Portal UI.

```bash
POST /v1/policies
{
  "name": "policy-name",
  "version": "1.0.0",
  "description": "Policy description",
  "rego_body": "package contextiq.policy_name\n..."
}
```

### 2. Validate

Validate policy syntax against OPA without persisting.

```bash
POST /v1/policies/validate
{
  "rego_body": "package contextiq.policy_name\n..."
}
```

### 3. Preview

Test the policy against recent execution traces to see impact.

```bash
POST /v1/policies/{id}/preview
```

### 4. Activate

Deploy the policy to production. Only one version can be active per policy group.

```bash
POST /v1/policies/{id}/activate
```

### 5. Monitor

Track policy evaluations, violations, and performance via:
- Admin Portal → Governance Dashboard
- Prometheus metrics: `policy_evaluations_total`, `policy_violations_total`
- Audit logs: `GET /v1/policies/{id}/audit`

### 6. Update/Rollback

Create a new version or rollback to a previous version.

```bash
# Create new version
POST /v1/policies
{
  "name": "existing-policy-name",
  "version": "1.1.0",
  ...
}

# Rollback
POST /v1/policies/{previous_version_id}/activate
```

## Writing Policies

### Policy Structure

```rego
package contextiq.policy_name

# Import Rego v1 syntax
import rego.v1

# Default deny
default allow := false

# Define rules
allow if {
    # Conditions for allowing request
}

# Denial reasons
deny_reason := "SPECIFIC_REASON" if {
    # Condition that triggers this reason
}

# Response structure
response := {
    "allow": allow,
    "deny_reason": deny_reason,
    "additional_data": {...}
}
```

### Input Schema

Policies receive a standardized input structure:

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
    "type": "string",
    "resource": "string",
    "action": "string"
  },
  "context": {
    "timestamp": "ISO-8601",
    "ip_address": "string",
    "session_id": "string"
  }
}
```

### Best Practices

1. **Default Deny**: Always start with `default allow := false`
2. **Explicit Rules**: Make conditions explicit and readable
3. **Structured Output**: Return structured responses with reasons
4. **Performance**: Keep rules efficient (< 10ms evaluation time)
5. **Documentation**: Document every rule and its purpose
6. **Testing**: Write comprehensive test cases
7. **Versioning**: Use semantic versioning (major.minor.patch)

## Testing Policies

### Local Testing with OPA CLI

```bash
# Install OPA
brew install opa  # macOS
# or download from https://www.openpolicyagent.org/docs/latest/#1-download-opa

# Validate syntax
opa check policy.rego

# Test with input
echo '{"input": {...}}' | opa eval -d policy.rego "data.contextiq.policy_name.allow"

# Run test suite
opa test policy.rego policy_test.rego -v
```

### Integration Testing

1. Deploy policy to staging environment
2. Run synthetic test cases via API
3. Verify audit logs and metrics
4. Test performance under load
5. Validate emergency override scenarios

## Deployment

### Via Admin Portal

1. Navigate to **Policies** page
2. Click **New Policy**
3. Fill in policy details and Rego code
4. Click **Validate** to check syntax
5. Click **Preview** to test against traces
6. Click **Save** to create draft
7. Click **Activate** to deploy

### Via API

See individual policy deployment guides in their respective directories.

### Via CI/CD

```yaml
# .github/workflows/deploy-policy.yml
name: Deploy Policy
on:
  push:
    paths:
      - 'docs/policies/*.rego'
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Validate Policy
        run: opa check docs/policies/*.rego
      - name: Deploy to Staging
        run: |
          curl -X POST $STAGING_API/v1/policies \
            -H "Authorization: Bearer $STAGING_TOKEN" \
            -d @policy-payload.json
      - name: Run Tests
        run: npm run test:policies
      - name: Deploy to Production
        if: success()
        run: |
          curl -X POST $PROD_API/v1/policies \
            -H "Authorization: Bearer $PROD_TOKEN" \
            -d @policy-payload.json
```

## Monitoring & Observability

### Key Metrics

- `policy_evaluations_total` - Total policy evaluations
- `policy_evaluations_duration_seconds` - Evaluation latency
- `policy_violations_total` - Total policy denials
- `policy_warnings_total` - Total warning conditions

### Dashboards

- **Governance Dashboard**: Real-time policy enforcement status
- **Policy Performance**: Evaluation latency and throughput
- **Compliance Report**: Violation trends and audit trail

### Alerts

Configure alerts in Prometheus/Alertmanager:

```yaml
groups:
  - name: policy_alerts
    rules:
      - alert: HighPolicyViolationRate
        expr: rate(policy_violations_total[5m]) > 10
        labels:
          severity: warning
        annotations:
          summary: "High policy violation rate detected"
```

## Troubleshooting

### Policy Not Enforcing

1. Check policy status: `GET /v1/policies/{id}`
2. Verify OPA service health: `curl http://opa:8181/health`
3. Review policy audit logs
4. Check governance agent logs

### Policy Evaluation Timeout

1. Optimize policy rules for performance
2. Increase OPA timeout configuration
3. Review policy complexity
4. Check OPA resource allocation

### Incorrect Policy Decision

1. Test with sample input via `/validate` endpoint
2. Review policy logic and rules
3. Check input data accuracy
4. Verify policy version is active

## Resources

### Documentation

- [OPA Documentation](https://www.openpolicyagent.org/docs/latest/)
- [Rego Language Guide](https://www.openpolicyagent.org/docs/latest/policy-language/)
- [OPA Best Practices](https://www.openpolicyagent.org/docs/latest/policy-testing/)
- [ContextIQ BRD - Policy Engine](../BRD.md#37-policy-engine)

### Tools

- [OPA Playground](https://play.openpolicyagent.org/) - Test policies online
- [Rego VS Code Extension](https://marketplace.visualstudio.com/items?itemName=tsandall.opa)
- [OPA CLI](https://www.openpolicyagent.org/docs/latest/#running-opa)

### Examples

- [OPA Example Policies](https://github.com/open-policy-agent/example-policies)
- [Kubernetes Admission Control](https://www.openpolicyagent.org/docs/latest/kubernetes-primer/)
- [Authorization Policies](https://www.openpolicyagent.org/docs/latest/comparison-to-other-systems/)

## Contributing

To contribute a new policy:

1. Create policy documentation (`.md`)
2. Implement policy in Rego (`.rego`)
3. Write test cases
4. Add deployment guide
5. Submit pull request with:
   - Policy purpose and rationale
   - Test results
   - Performance benchmarks
   - Security considerations

## Support

For questions or issues:

- Check [Troubleshooting](#troubleshooting) section
- Review policy audit logs in Admin Portal
- Contact platform team
- Open issue in ContextIQ repository
