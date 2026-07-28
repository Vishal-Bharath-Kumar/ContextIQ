# Policies vs Governance in ContextIQ

## 📋 Quick Comparison

| Aspect | **Policies** (OPA/Rego) | **Governance** (Security Scanning) |
|--------|--------------------------|-------------------------------------|
| **What** | Business rules & authorization logic | Security & compliance validation |
| **When** | Before/during request processing | After context retrieval, before LLM |
| **How** | OPA policy engine evaluating rules | Pattern detection + validators |
| **Format** | Rego policy language | Pre-compiled regex + validators |
| **Scope** | Budget, access, quotas, routing | Secrets, PII, compliance, RBAC |
| **Output** | Allow/Deny with reason | Allow/Mask/Block with findings |
| **Configurable** | Write custom Rego policies | Toggle patterns, adjust thresholds |
| **Versioning** | Full version history (draft→active) | Real-time configuration changes |

---

## 🎯 **Policies** - Business Logic & Authorization

### What Are Policies?

**Open Policy Agent (OPA) policies** written in **Rego** that define **business rules** for how the AI platform operates. Think of them as **"the rules of the game"** - they determine **who can do what, when, and at what cost**.

### Technology Stack
- **OPA** (Open Policy Agent) - Policy evaluation engine
- **Rego** - Declarative policy language
- **Versioning** - Full audit trail of policy changes
- **Bundling** - Policies pushed to OPA as bundles

### Use Cases

#### 1. **Budget & Cost Controls**
```rego
# Block requests that exceed cost limits
allow if {
    input.request.estimated_cost_usd <= input.limits.request_max_usd
    input.current_spending.user_daily_usd < input.limits.user_daily_max_usd
}
```

**Example:** Prevent developers from using expensive GPT-4 models after spending $100/day

#### 2. **Access Control & Authorization**
```rego
# Only allow admins to access production data
allow if {
    input.user.role == "Administrator"
    input.request.data_classification == "PRODUCTION"
}
```

**Example:** Restrict junior developers from querying sensitive customer data

#### 3. **Rate Limiting & Quotas**
```rego
# Limit analysts to 100 queries per hour
allow if {
    input.user.role == "Analyst"
    input.current_usage.queries_last_hour < 100
}
```

**Example:** Prevent abuse by limiting requests per user/department

#### 4. **Model Routing & Selection**
```rego
# Route cheap queries to local Ollama, expensive to cloud
route_to := model if {
    input.request.complexity == "simple"
    model := "ollama/llama3.2"
} else := model if {
    input.request.complexity == "complex"
    model := "openai/gpt-4o"
}
```

**Example:** Optimize costs by routing simple queries to free local models

#### 5. **Time-Based Restrictions**
```rego
# Block non-critical requests during peak hours
allow if {
    not is_peak_hours
    input.request.priority != "critical"
}
```

**Example:** Limit batch jobs to off-peak hours to preserve resources

#### 6. **Compliance & Regulatory Rules**
```rego
# Require data residency for EU users
allow if {
    input.user.region == "EU"
    input.model.location in ["eu-west-1", "eu-central-1"]
}
```

**Example:** GDPR compliance - EU data stays in EU data centers

### Workflow

```
Request arrives
    ↓
┌─────────────────────────────────────┐
│  OPA Policy Evaluation              │
│                                     │
│  1. Load active policy bundle       │
│  2. Evaluate Rego rules             │
│  3. Input: user, request, context   │
│  4. Output: allow/deny + reason     │
└─────────────────────────────────────┘
    ↓
Allow? → Proceed with request
Deny?  → Return 403 Forbidden
```

### Admin UI Features

**Location:** http://localhost:3000/policies

1. **Create New Policy**
   - Write Rego policy in browser
   - Validate syntax against OPA
   - Save as draft

2. **Version Management**
   - Multiple versions per policy
   - Status: draft → active → superseded
   - Full audit trail (author, timestamps)

3. **Activate/Deactivate**
   - Promote draft → active
   - Push to OPA automatically
   - Only one version active at a time

4. **Preview Impact**
   - Test policy against recent traces
   - See allow/deny percentages
   - Identify breaking changes before activation

5. **Rollback**
   - Restore previous version
   - Automatic OPA bundle update
   - Safety net for bad policy changes

### Policy Lifecycle

```
Draft Policy
    ↓
[Validate Rego]
    ↓
[Preview Impact] ← Test against historical data
    ↓
[Activate] → Push to OPA
    ↓
Active Policy (enforced)
    ↓
[New version created] → Old version becomes "superseded"
    ↓
[Rollback available] ← Restore old version if needed
```

### Example Policy: Budget Limits

```rego
package contextiq.budget_limits

default allow := false

# Allow if user hasn't exceeded daily budget
allow if {
    input.current_spending.user_daily_usd + input.request.estimated_cost_usd 
    <= input.limits.user_daily_max_usd
}

# Emergency override for critical requests
allow if {
    input.user.role in ["Administrator", "SRE"]
    input.request.priority == "critical"
}

# Provide detailed denial reason
deny_reason := "DAILY_LIMIT_EXCEEDED" if {
    input.current_spending.user_daily_usd >= input.limits.user_daily_max_usd
}
```

**Result when evaluated:**
```json
{
  "allow": false,
  "deny_reason": "DAILY_LIMIT_EXCEEDED",
  "budget_status": {
    "remaining_daily": 0.00,
    "remaining_monthly": 350.00,
    "warnings": ["APPROACHING_MONTHLY_LIMIT"]
  }
}
```

---

## 🛡️ **Governance** - Security & Compliance Scanning

### What Is Governance?

An **automated security gate** that **scans content** for secrets, PII, and compliance violations **before it reaches the LLM**. Think of it as **"airport security"** - it inspects everything passing through and blocks dangerous items.

### Technology Stack
- **Pattern Detection** - 38 pre-compiled regex patterns
- **Compliance Validators** - GDPR, SOC2, HIPAA, PCI-DSS, CCPA
- **RBAC Validator** - Role-based access control
- **Risk Scoring** - Weighted severity calculation
- **Context Redaction** - Automatic masking of findings

### Use Cases

#### 1. **Secret Detection**
```
Input: "My AWS key is AKIAIOSFODNN7EXAMPLE"

Detection:
✗ CRITICAL: AWS_ACCESS_KEY found
→ Action: BLOCK or MASK
→ Output: "My AWS key is <REDACTED:AWS_ACCESS_KEY>"
```

**Example:** Prevent developers from accidentally exposing API keys in queries

#### 2. **PII Protection**
```
Input: "Customer SSN: 123-45-6789, Card: 4532-1234-5678-9010"

Detection:
✗ HIGH: SSN detected
✗ HIGH: CREDIT_CARD detected (Luhn validated)
→ Action: MASK + ALERT
→ Output: "Customer SSN: <REDACTED:SSN>, Card: <REDACTED:CREDIT_CARD>"
```

**Example:** Comply with GDPR/CCPA by automatically masking personal data

#### 3. **Compliance Validation**
```
Findings: 1 × CREDIT_CARD (HIGH)

Compliance Check:
⚠️ PCI-DSS VIOLATION:
   Rule: REQ_3.4 (Cardholder data masking)
   Severity: HIGH
   Risk Score: 3.5

→ Action: MASK + COMPLIANCE ALERT
```

**Example:** Ensure credit cards are never sent to LLMs (PCI-DSS requirement)

#### 4. **RBAC Enforcement**
```
User: john.doe@company.com
Role: DEVELOPER
Data Classification: SECRET
Required Permission: READ

RBAC Check:
✗ DEVELOPER cannot access SECRET data
→ Action: BLOCK (empty context)
```

**Example:** Prevent developers from accessing executive/financial data

#### 5. **Risk-Based Enforcement**
```
Findings:
- 2 × CRITICAL (AWS keys)
- 1 × HIGH (SSN)
- 3 × MEDIUM (emails)

Risk Score: 2×5.0 + 1×3.0 + 3×1.5 = 17.5 → 10.0 (CRITICAL)

→ Action: BLOCK + ADMIN ALERT
```

**Example:** Automatically block high-risk content from reaching AI models

### Workflow

```
Context retrieved from knowledge sources
    ↓
┌─────────────────────────────────────────────┐
│  Governance Gate (Mandatory)                │
│                                             │
│  1. Pattern Detection (38 patterns, 145ms) │
│  2. Compliance Validation (5 standards)    │
│  3. RBAC Validation (role × permission)    │
│  4. Risk Scoring (0-10 scale)              │
│  5. Enforcement Decision                   │
│     - LOW: Allow + Log                     │
│     - MEDIUM: Mask secrets                 │
│     - HIGH: Mask + Alert                   │
│     - CRITICAL: Block + Alert              │
│  6. Context Redaction (if needed)          │
│  7. Audit Logging                          │
└─────────────────────────────────────────────┘
    ↓
Approved/Redacted context → LLM
Blocked context → Error response
```

### Admin UI Features

**Location:** http://localhost:3000/governance

**Tab 1: Compliance Standards**
- Toggle GDPR, SOC2, HIPAA, PCI-DSS, CCPA on/off
- View requirement counts per standard

**Tab 2: RBAC & Permissions**
- Visual matrix: 5 roles × 6 permissions
- Data classification access levels
- Real-time permission updates

**Tab 3: Pattern Detection**
- 38 patterns across 7 categories
- Search/filter by name or category
- Bulk enable/disable by category
- Individual pattern toggles
- Severity badges (CRITICAL, HIGH, MEDIUM, LOW, INFO)

**Tab 4: Risk Scoring**
- Adjust severity weights (0.1 - 5.0)
- Set violation penalties
- Configure risk thresholds
- Live calculation preview

### Governance Lifecycle

```
Content arrives (ranked_context)
    ↓
[Pattern Scan: 145ms]
    ↓
[Findings Detected: 3 CRITICAL, 1 HIGH]
    ↓
[Compliance: SOC2 VIOLATION]
    ↓
[RBAC: AUTHORIZED (Developer role)]
    ↓
[Risk Score: 6.5 (HIGH)]
    ↓
[Decision: MASK + ALERT]
    ↓
[Redact Secrets: AKIA... → <REDACTED>]
    ↓
[Audit Log: Store for 90 days]
    ↓
[Send to LLM: Safe, redacted content]
```

### Example Governance Scan

**Input Context:**
```
Here's how to configure AWS:
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG...
Contact support@company.com for help.
```

**Governance Analysis:**
```
Pattern Detection (145ms):
✗ CRITICAL: AWS_ACCESS_KEY detected (line 2)
✗ CRITICAL: AWS_SECRET_KEY detected (line 3)
ℹ MEDIUM: EMAIL detected (line 4)

Compliance Validation:
⚠️ SOC2 VIOLATION (CC6.1 - Logical Access Control)
   Severity: HIGH
   Reason: Hardcoded AWS credentials

RBAC Validation:
✓ User: john.doe@company.com (DEVELOPER role)
✓ Permission: READ, DEBUG
✓ Classification: INTERNAL
→ AUTHORIZED

Risk Scoring:
2 × CRITICAL (5.0) = 10.0
1 × MEDIUM (1.5) = 1.5
Violations: 1 × 0.5 = 0.5
Total: 12.0 → clamped to 10.0 (CRITICAL)

Enforcement Decision:
Risk: CRITICAL (10.0)
→ Action: BLOCK + ADMIN ALERT
```

**Output:**
```json
{
  "status": "blocked",
  "reason": "Critical security findings detected",
  "risk_score": 10.0,
  "risk_level": "CRITICAL",
  "findings": [
    {
      "type": "AWS_ACCESS_KEY",
      "severity": "CRITICAL",
      "line": 2
    },
    {
      "type": "AWS_SECRET_KEY",
      "severity": "CRITICAL",
      "line": 3
    }
  ],
  "compliance_violations": [
    {
      "standard": "SOC2",
      "rule": "CC6.1"
    }
  ],
  "action_required": "Remove credentials from content"
}
```

---

## 🔄 How They Work Together

### Request Flow

```
1. User submits query
       ↓
2. [POLICY CHECK] ← Can user make this request?
   - Budget limits
   - Rate limits
   - Authorization rules
   - Model routing
       ↓
   Allow? → Continue
   Deny?  → Return 403 with policy reason
       ↓
3. Retrieve context from knowledge sources
       ↓
4. [GOVERNANCE SCAN] ← Is content safe?
   - Secret detection
   - PII protection
   - Compliance validation
   - RBAC enforcement
       ↓
   Safe?      → Send original/redacted to LLM
   Unsafe?    → Block or mask
       ↓
5. LLM generates response
       ↓
6. Return to user
```

### Example: Complete Request

**Scenario:** Junior developer queries customer database

```
Request: "Show me customer data for user ID 12345"

── POLICY EVALUATION ──────────────────────────

Input to OPA:
{
  "user": {
    "email": "junior.dev@company.com",
    "role": "Developer",
    "department": "Engineering"
  },
  "request": {
    "query": "customer data",
    "data_classification": "CONFIDENTIAL",
    "estimated_cost": 0.05
  },
  "current_spending": {
    "user_daily_usd": 5.50
  },
  "limits": {
    "user_daily_max_usd": 50.00
  }
}

Policy Result:
✓ ALLOW (budget OK, role authorized for CONFIDENTIAL)

── KNOWLEDGE RETRIEVAL ────────────────────────

Retrieved context:
"Customer ID: 12345
Name: John Smith
Email: john.smith@example.com
Phone: (555) 123-4567
SSN: 123-45-6789
Credit Card: 4532-1234-5678-9010
Account Balance: $15,234.56"

── GOVERNANCE SCAN ────────────────────────────

Pattern Detection:
ℹ MEDIUM: EMAIL detected
ℹ MEDIUM: PHONE detected
✗ HIGH: SSN detected
✗ HIGH: CREDIT_CARD detected (Luhn validated)

Compliance Validation:
⚠️ GDPR: Personal data requires consent
⚠️ PCI-DSS: Credit card must be masked

RBAC Validation:
✓ Developer role can access CONFIDENTIAL data

Risk Scoring:
2 × HIGH (3.0) = 6.0
2 × MEDIUM (1.5) = 3.0
Violations: 2 × 0.5 = 1.0
Total: 10.0 (CRITICAL)

Enforcement Decision:
Risk: CRITICAL (10.0)
→ Action: MASK HIGH findings + ALERT

Redacted Context:
"Customer ID: 12345
Name: John Smith
Email: john.smith@example.com
Phone: (555) 123-4567
SSN: <REDACTED:SSN>
Credit Card: <REDACTED:CREDIT_CARD>
Account Balance: $15,234.56"

── LLM RESPONSE ───────────────────────────────

LLM receives REDACTED context (safe)
Generates response without sensitive data

── AUDIT TRAIL ────────────────────────────────

Stored for 90 days:
- Policy: "budget_limits" allowed request
- Governance: Blocked 2 HIGH findings
- Compliance tags: GDPR, PCI-DSS
- Risk score: 10.0 (CRITICAL)
- Action: MASK + ALERT
```

---

## 🎯 When to Use Which?

### Use **Policies** (OPA/Rego) For:

✅ **Business Logic**
- "Developers can spend up to $100/day"
- "Analysts limited to 50 queries/hour"
- "Only admins can access production data"

✅ **Cost Management**
- Budget limits per user/department
- Model routing based on cost
- Request size limits

✅ **Authorization**
- Role-based access rules
- Time-based restrictions
- Department-specific permissions

✅ **Resource Management**
- Rate limiting
- Quota enforcement
- Fair-use policies

✅ **Custom Business Rules**
- Anything requiring complex logic
- Multi-condition authorization
- Dynamic routing/selection

### Use **Governance** (Security Scanning) For:

✅ **Security Protection**
- Detecting secrets (API keys, passwords)
- Finding hardcoded credentials
- Identifying access tokens

✅ **Privacy Compliance**
- PII detection (SSN, credit cards)
- GDPR compliance
- CCPA requirements

✅ **Regulatory Compliance**
- SOC2 controls
- HIPAA requirements
- PCI-DSS standards

✅ **Data Classification**
- RBAC enforcement
- Classification-based access
- Role permission validation

✅ **Automated Protection**
- Real-time secret masking
- Automatic PII redaction
- Risk-based blocking

---

## 📊 Key Differences Summary

### **Policies** = **"Can you do this?"**
- Authorization engine
- Evaluates business rules
- Returns allow/deny
- Custom Rego logic
- Version-controlled
- OPA-powered

### **Governance** = **"Is this content safe?"**
- Security scanner
- Detects secrets/PII
- Returns allow/mask/block
- Pre-built patterns
- Real-time config
- Pattern-matching + validators

---

## 🚀 Best Practices

### For Policies:
1. **Start simple** - Basic budget/quota rules first
2. **Version carefully** - Always preview before activating
3. **Document well** - Comment your Rego policies
4. **Test thoroughly** - Use policy preview feature
5. **Keep rollback ready** - Monitor after activation

### For Governance:
1. **Start strict** - Enable all critical patterns
2. **Tune gradually** - Adjust thresholds based on findings
3. **Monitor alerts** - Review high-risk detections
4. **Train teams** - Explain why secrets are blocked
5. **Regular audits** - Review 90-day audit logs

---

## 📚 Related Documentation

- [Governance Workflow](./GOVERNANCE_WORKFLOW.md) - Complete governance system details
- [Governance Diagrams](./GOVERNANCE_DIAGRAMS.md) - Visual flowcharts
- [Policy API Reference](./docs/api/policies.md) - Policy endpoints
- [Governance API Reference](./docs/api/governance.md) - Governance endpoints

---

**Version:** 1.0.0  
**Last Updated:** 2026-07-29  
**Authors:** ContextIQ Security & Engineering Teams
