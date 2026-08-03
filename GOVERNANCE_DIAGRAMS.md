```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Query as Query Processing
    participant KG as Knowledge Graph
    participant Gov as Governance Gate
    participant LLM
    participant Audit as Audit Log

    User->>Query: Submit query with context
    Query->>KG: Retrieve & rank documents
    KG->>Gov: Send ranked_context (10-20 chunks)
    
    rect rgb(255, 240, 240)
        Note over Gov: 🛡️ GOVERNANCE GATE (Mandatory)
        
        Gov->>Gov: 1. Pattern Detection<br/>(38 regex patterns)
        alt Timeout (>5s)
            Gov->>Audit: Log timeout failure
            Gov-->>LLM: ❌ Empty context (fail-safe)
        else Success
            Gov->>Gov: 2. Compliance Validation<br/>(GDPR, SOC2, HIPAA, PCI, CCPA)
            Gov->>Gov: 3. RBAC Validation<br/>(Role × Permission × Classification)
            
            alt RBAC Denied
                Gov->>Audit: Log RBAC denial
                Gov-->>LLM: ❌ Empty context (blocked)
            else RBAC Authorized
                Gov->>Gov: 4. Risk Scoring<br/>(Severity weights + violations)
                
                alt Risk: CRITICAL (>8.0)
                    Gov->>Audit: Log critical risk + alert
                    Gov-->>LLM: ❌ Empty context (blocked)
                else Risk: HIGH (5.1-8.0)
                    Gov->>Gov: 5a. Redact CRITICAL+HIGH findings
                    Gov->>Audit: Log masking + alert
                    Gov-->>LLM: ⚠️ Redacted context
                else Risk: MEDIUM (2.1-5.0)
                    Gov->>Gov: 5b. Redact CRITICAL+HIGH findings
                    Gov->>Audit: Log masking
                    Gov-->>LLM: ⚠️ Redacted context
                else Risk: LOW (0-2.0)
                    Gov->>Audit: Log allow decision
                    Gov-->>LLM: ✅ Original context
                end
            end
        end
    end
    
    LLM->>LLM: Generate response
    LLM->>User: Return answer (safe)
    
    Note over Audit: Stored for 90 days<br/>Compliance tags: GDPR, SOC2, etc.
```

---

```mermaid
flowchart TD
    Start([User Query + Retrieved Context]) --> Scan[Pattern Detection Engine<br/>38 regex patterns]
    
    Scan --> Timeout{Scan<br/>Timeout?}
    Timeout -->|Yes >5s| Block1[❌ BLOCK<br/>Empty context]
    Timeout -->|No| Findings[Findings Detected]
    
    Findings --> Compliance[Compliance Validation<br/>GDPR • SOC2 • HIPAA<br/>PCI-DSS • CCPA]
    Compliance --> RBAC[RBAC Validation<br/>Role × Permission × Classification]
    
    RBAC --> RBACCheck{RBAC<br/>Authorized?}
    RBACCheck -->|No| Block2[❌ BLOCK<br/>RBAC denied]
    RBACCheck -->|Yes| Risk[Risk Scoring<br/>Severity weights + violations]
    
    Risk --> RiskLevel{Risk<br/>Level?}
    
    RiskLevel -->|CRITICAL<br/>>8.0| Block3[❌ BLOCK<br/>Alert admin]
    RiskLevel -->|HIGH<br/>5.1-8.0| Redact1[🔶 MASK + ALERT<br/>Redact CRITICAL+HIGH]
    RiskLevel -->|MEDIUM<br/>2.1-5.0| Redact2[⚠️ MASK<br/>Redact CRITICAL+HIGH]
    RiskLevel -->|LOW<br/>0.0-2.0| Allow[✅ ALLOW<br/>Log only]
    
    Block1 --> Audit1[(Audit Log:<br/>Timeout failure)]
    Block2 --> Audit2[(Audit Log:<br/>RBAC denial)]
    Block3 --> Audit3[(Audit Log:<br/>Critical risk)]
    Redact1 --> Audit4[(Audit Log:<br/>High risk + masking)]
    Redact2 --> Audit5[(Audit Log:<br/>Medium risk + masking)]
    Allow --> Audit6[(Audit Log:<br/>Low risk)]
    
    Audit1 --> LLM1[LLM receives:<br/>Empty context]
    Audit2 --> LLM1
    Audit3 --> LLM1
    Audit4 --> LLM2[LLM receives:<br/>Redacted context]
    Audit5 --> LLM2
    Audit6 --> LLM3[LLM receives:<br/>Original context]
    
    LLM1 --> Response1([Response:<br/>Blocked])
    LLM2 --> Response2([Response:<br/>Safe, no secrets])
    LLM3 --> Response3([Response:<br/>Complete])
    
    style Scan fill:#e1f5ff
    style Compliance fill:#fff4e1
    style RBAC fill:#ffe1f5
    style Risk fill:#f5e1ff
    style Block1 fill:#ffcccc
    style Block2 fill:#ffcccc
    style Block3 fill:#ffcccc
    style Redact1 fill:#ffe4cc
    style Redact2 fill:#fff5cc
    style Allow fill:#ccffcc
```

---

```mermaid
graph TB
    subgraph Admin["👤 Admin Configuration (UI)"]
        Comp[Compliance Standards<br/>✓ GDPR ✓ SOC2 ✗ HIPAA<br/>✓ PCI-DSS ✗ CCPA]
        Roles[RBAC Permissions<br/>5 Roles × 6 Permissions<br/>5 Classification Levels]
        Patterns[Pattern Detection<br/>38 Patterns / 7 Categories<br/>Individual enable/disable]
        Scoring[Risk Scoring<br/>Severity weights 0.1-5.0<br/>Violation penalty]
    end
    
    subgraph Runtime["⚙️ Runtime Governance"]
        Detector[SecretPIIDetector<br/>Pre-compiled regex<br/><200ms scan time]
        CompVal[ComplianceValidator<br/>Map findings → standards<br/>Calculate violations]
        RBACVal[RBACValidator<br/>Check role + permission<br/>Verify classification]
        RiskCalc[Risk Calculator<br/>Weighted sum<br/>0-10 scale]
        Enforcer[Enforcement Engine<br/>ALLOW / MASK / BLOCK<br/>Context redaction]
    end
    
    subgraph Outputs["📊 Outputs"]
        Trace[Execution Trace<br/>Finding details<br/>Timestamps]
        OTel[OpenTelemetry Spans<br/>Distributed tracing<br/>Metrics]
        Lang[Langfuse Events<br/>AI observability<br/>Pattern metadata]
        AuditDB[(Audit Database<br/>90-day retention<br/>Compliance tags)]
    end
    
    Comp -.Config.-> CompVal
    Roles -.Config.-> RBACVal
    Patterns -.Config.-> Detector
    Scoring -.Config.-> RiskCalc
    
    Detector --> CompVal
    CompVal --> RiskCalc
    Detector --> RBACVal
    RBACVal --> RiskCalc
    RiskCalc --> Enforcer
    
    Enforcer --> Trace
    Enforcer --> OTel
    Enforcer --> Lang
    Enforcer --> AuditDB
    
    style Comp fill:#e3f2fd
    style Roles fill:#f3e5f5
    style Patterns fill:#e8f5e9
    style Scoring fill:#fff3e0
    style Detector fill:#ffebee
    style Enforcer fill:#fce4ec
    style AuditDB fill:#e0f2f1
```

---

## Legend

**Risk Levels:**
- 🟢 **LOW** (0.0 - 2.0): Allow with logging only
- 🟡 **MEDIUM** (2.1 - 5.0): Allow with masking
- 🟠 **HIGH** (5.1 - 8.0): Allow with masking + alert
- 🔴 **CRITICAL** (8.1 - 10.0): Block + alert

**Actions:**
- ✅ **ALLOW**: Context passes through unchanged
- ⚠️ **MASK**: Critical/High findings redacted
- 🔶 **MASK + ALERT**: Redaction + notification
- ❌ **BLOCK**: Empty context sent to LLM

**Severity Levels:**
- **CRITICAL**: Secrets, API keys, passwords (weight: 5.0)
- **HIGH**: SSN, credit cards, private keys (weight: 3.0)
- **MEDIUM**: Emails, phone numbers (weight: 1.5)
- **LOW**: Common patterns (weight: 0.5)
- **INFO**: IP addresses (weight: 0.1)
