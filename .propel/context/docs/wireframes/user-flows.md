# ContextIQ — User Flow Diagrams

## Metadata

| Field | Value |
|---|---|
| Document Type | User Flow Diagrams |
| Version | 1.0 |
| Source | `figma_spec_contextiq.md` Part 7 — Interaction Flows |

---

## Flow 1 — Add Connector

**Actor:** Platform Engineer / Admin  
**Goal:** Register a new external data connector so the platform can ingest from it.

```mermaid
flowchart TD
    F1_START([Start]) --> F1_NAV["Navigate to /connectors"]
    F1_NAV --> F1_LIST["CONN-001: View Connector List"]
    F1_LIST --> F1_CLICK["Click 'Add Connector' button"]
    F1_CLICK --> F1_FORM["CONN-002: Add Connector Form\n(slide-over drawer)"]
    F1_FORM --> F1_SELECT["Select connector type\n(SQL DB / REST / gRPC / File)"]
    F1_SELECT --> F1_FILL["Fill connection details\n(host, port, credentials, schema)"]
    F1_FILL --> F1_TEST["Click 'Test Connection'"]
    F1_TEST --> F1_DECIDE{Connection\nsucceeds?}
    F1_DECIDE -->|Failure| F1_ERR["Show inline error\n(error message + retry hint)"]
    F1_ERR --> F1_FILL
    F1_DECIDE -->|Success| F1_GREEN["Show green 'Connection OK' badge"]
    F1_GREEN --> F1_SAVE["Click 'Save Connector'"]
    F1_SAVE --> F1_API["POST /api/v1/connectors\n→ 201 Created"]
    F1_API --> F1_TOAST["Show success toast\n'Connector registered'"]
    F1_TOAST --> F1_REDIRECT["Redirect to CONN-003\nConnector Health detail"]
    F1_REDIRECT --> F1_END([End])

    style F1_ERR fill:#3d1a1a,stroke:#b91c1c,color:#fca5a5
    style F1_GREEN fill:#1a3d1a,stroke:#16a34a,color:#86efac
    style F1_TOAST fill:#1a2c3d,stroke:#2563eb,color:#93c5fd
```

---

## Flow 2 — Policy Lifecycle

**Actor:** Security Officer / Admin  
**Goal:** Author, test, and activate a Rego policy that governs AI agent behavior.

```mermaid
flowchart TD
    F2_START([Start]) --> F2_NAV["Navigate to /policies"]
    F2_NAV --> F2_LIST["POL-001: Policy List"]
    F2_LIST --> F2_BRANCH{New or\nExisting?}

    F2_BRANCH -->|New| F2_CREATE["Click 'New Policy' button"]
    F2_CREATE --> F2_EDITOR["POL-002: Policy Editor\n(blank Monaco editor)"]
    F2_BRANCH -->|Existing| F2_CLICK_ROW["Click policy row"]
    F2_CLICK_ROW --> F2_EDITOR_LOADED["POL-002: Policy Editor\n(pre-populated)"]

    F2_EDITOR --> F2_WRITE["Write Rego code\nin Monaco editor"]
    F2_EDITOR_LOADED --> F2_WRITE

    F2_WRITE --> F2_LINT["Auto-lint on change\n(500 ms debounce)"]
    F2_LINT --> F2_LINT_OK{Lint\npasses?}
    F2_LINT_OK -->|No| F2_LINT_ERR["Show inline gutter error\nand error panel"]
    F2_LINT_ERR --> F2_WRITE
    F2_LINT_OK -->|Yes| F2_SIM_TRIGGER["Click 'Test in Simulation'"]

    F2_SIM_TRIGGER --> F2_SIM["POL-003: Policy Simulation\nInput payload editor"]
    F2_SIM --> F2_RUN["Enter test payload JSON\nClick 'Run'"]
    F2_RUN --> F2_RESULT{Policy\ndecision}
    F2_RESULT -->|DENY| F2_DENY["Result panel:\nDENY + binding path"]
    F2_RESULT -->|ALLOW| F2_ALLOW["Result panel:\nALLOW + matched rules"]

    F2_DENY --> F2_BACK_EDIT["Return to editor, revise"]
    F2_BACK_EDIT --> F2_WRITE

    F2_ALLOW --> F2_ACTIVATE["Return to POL-002\nClick 'Activate'"]
    F2_ACTIVATE --> F2_CONFIRM["Confirmation modal\n'Activate policy?'"]
    F2_CONFIRM --> F2_PATCH["PATCH /api/v1/policies/:id\nbody: {active: true}"]
    F2_PATCH --> F2_STATUS["Policy row shows\n'Active' badge"]
    F2_STATUS --> F2_END([End])

    style F2_LINT_ERR fill:#3d1a1a,stroke:#b91c1c,color:#fca5a5
    style F2_DENY fill:#3d1a1a,stroke:#b91c1c,color:#fca5a5
    style F2_ALLOW fill:#1a3d1a,stroke:#16a34a,color:#86efac
    style F2_STATUS fill:#1a3d1a,stroke:#16a34a,color:#86efac
```

---

## Flow 3 — Replay Drill-Down

**Actor:** Auditor / DevOps SRE / Admin  
**Goal:** Investigate a specific AI agent trace by stepping through each phase to locate the root cause of a decision or failure.

```mermaid
flowchart TD
    F3_START([Start]) --> F3_NAV["Navigate to /traces"]
    F3_NAV --> F3_LIST["REPLAY-001: Trace List\n(time-range, status, model filters)"]
    F3_LIST --> F3_SEARCH["Apply filters:\ndate range, trace status\nagent model, session ID"]
    F3_SEARCH --> F3_SELECT["Click trace row"]
    F3_SELECT --> F3_TIMELINE["REPLAY-002: Trace Timeline\n(horizontal swimlane)"]
    F3_TIMELINE --> F3_SCAN["Scan phase swimlanes:\nPLAN / RETRIEVE / REASON / GENERATE / EVAL"]
    F3_SCAN --> F3_CLICK_PHASE["Click suspicious phase segment"]
    F3_CLICK_PHASE --> F3_DRAWER["REPLAY-003: Phase Detail Drawer\n(slides in from right)"]
    F3_DRAWER --> F3_REVIEW["Review:\n- Input / Output tokens\n- Latency ms\n- Context window\n- Policy evaluation result\n- Embedding vector (truncated)"]
    F3_REVIEW --> F3_DECIDE{Root cause\nfound?}
    F3_DECIDE -->|No| F3_CLOSE_DRAWER["Close drawer"]
    F3_CLOSE_DRAWER --> F3_CLICK_PHASE
    F3_DECIDE -->|Yes| F3_EXPORT["Click 'Export Trace'\n(JSON download)"]
    F3_EXPORT --> F3_END([End])

    style F3_DRAWER fill:#1a2030,stroke:#6366f1,color:#c7d2fe
```

---

## Flow 4 — Audit Log Review + Integrity Check

**Actor:** Auditor / Security Officer / Admin  
**Goal:** Review platform mutation events and cryptographically verify the hash chain is unbroken.

```mermaid
flowchart TD
    F4_START([Start]) --> F4_NAV["Navigate to /audit-log"]
    F4_NAV --> F4_TABLE["AUDIT-001: Audit Log Table\n(newest-first, 50 rows/page)"]
    F4_TABLE --> F4_FILTER["Apply filters:\naction type, actor email,\nresource type, date range"]
    F4_FILTER --> F4_SCAN["Scan rows for suspicious events\n(e.g. POLICY_DELETED, CONNECTOR_EDITED)"]
    F4_SCAN --> F4_EXPAND["Click row to expand\nbefore_state / after_state JSON diff"]
    F4_EXPAND --> F4_LOAD_MORE{More rows\nneeded?}
    F4_LOAD_MORE -->|Yes| F4_SCROLL["Scroll to bottom\n→ 'Load more' fires cursor-paginated fetch"]
    F4_SCROLL --> F4_SCAN
    F4_LOAD_MORE -->|No| F4_INTEGRITY["Navigate to /audit-log/verify\nor click 'Verify Integrity' button"]
    F4_INTEGRITY --> F4_VERIFY_SCREEN["AUDIT-002: Chain Integrity Screen"]
    F4_VERIFY_SCREEN --> F4_RUN_VERIFY["Click 'Run Verification'\n(GET /api/v1/audit-log/verify)"]
    F4_RUN_VERIFY --> F4_LOADING["Spinner while hashing\n(backend re-computes full chain)"]
    F4_LOADING --> F4_RESULT{Chain\nintegrity}
    F4_RESULT -->|VALID| F4_GREEN_BADGE["Show 'Chain Valid ✓'\nbadge + row count verified"]
    F4_RESULT -->|TAMPERED| F4_RED_BADGE["Show 'Tampering Detected ✗'\nfirst divergence row + hash mismatch detail"]
    F4_GREEN_BADGE --> F4_END([End])
    F4_RED_BADGE --> F4_ESCALATE["Escalation CTA:\n'Download evidence' + 'Notify SIEM'"]
    F4_ESCALATE --> F4_END

    style F4_GREEN_BADGE fill:#1a3d1a,stroke:#16a34a,color:#86efac
    style F4_RED_BADGE fill:#3d1a1a,stroke:#b91c1c,color:#fca5a5
```

---

## Flow 5 — Connector Status Update (Automated)

**Actor:** System (automated health-check daemon)  
**Goal:** Platform monitors connector health; UI reflects live status changes without page reload.

```mermaid
flowchart TD
    F5_START([Health-check daemon tick]) --> F5_PROBE["Probe connector endpoint\n(TCP/HTTP/SQL ping)"]
    F5_PROBE --> F5_RESULT{Probe\nresult}
    F5_RESULT -->|Healthy| F5_HEALTHY_DB["Write status=HEALTHY\nto connector record"]
    F5_RESULT -->|Unreachable| F5_UNHEALTHY_DB["Write status=UNHEALTHY\nerror_message = probe error"]
    F5_RESULT -->|Degraded| F5_DEGRADED_DB["Write status=DEGRADED\nlatency > threshold"]

    F5_HEALTHY_DB --> F5_EMIT["Emit WebSocket event\nconnector:status_changed"]
    F5_UNHEALTHY_DB --> F5_EMIT
    F5_DEGRADED_DB --> F5_EMIT

    F5_EMIT --> F5_CLIENT["Browser receives WS event"]
    F5_CLIENT --> F5_UPDATE["React Query cache\ninvalidated for /connectors"]
    F5_UPDATE --> F5_BADGE["StatusBadge component\nupdates in CONN-001 list row"]
    F5_BADGE --> F5_TOAST_Q{Status\nchange severity?}
    F5_TOAST_Q -->|HEALTHY to UNHEALTHY| F5_ALERT_TOAST["Show alert toast\n'Connector X went offline'"]
    F5_TOAST_Q -->|UNHEALTHY to HEALTHY| F5_RECOVERY_TOAST["Show info toast\n'Connector X recovered'"]
    F5_TOAST_Q -->|Minor change| F5_SILENT["Silent badge update\n(no toast)"]

    F5_ALERT_TOAST --> F5_END([End])
    F5_RECOVERY_TOAST --> F5_END
    F5_SILENT --> F5_END

    style F5_ALERT_TOAST fill:#3d1a1a,stroke:#b91c1c,color:#fca5a5
    style F5_RECOVERY_TOAST fill:#1a3d1a,stroke:#16a34a,color:#86efac
```

---

*Source: `figma_spec_contextiq.md` Part 7 — Interaction Flows*
