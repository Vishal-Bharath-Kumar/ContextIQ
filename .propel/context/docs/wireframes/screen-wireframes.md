# ContextIQ — Screen Wireframes

## Metadata

| Field | Value |
|---|---|
| Document Type | Screen Wireframes (Lo-Fidelity) |
| Version | 1.0 |
| Fidelity | Low — structural layout + component annotation |
| Viewport | 1280 × 900 (desktop baseline) |
| Source | `figma_spec_contextiq.md` Parts 5, 6 |

## Reading Guide

Each wireframe section contains:
1. **ASCII layout grid** — structural positioning at the 1280px breakpoint
2. **Component annotation table** — each labelled zone mapped to design system component, token, and interaction note
3. **State inventory** — all UI states the screen must handle

Symbols used in ASCII grids:

| Symbol | Meaning |
|---|---|
| `░░░` | Placeholder / content area |
| `[  ]` | Interactive element (button, input) |
| `{ }` | Icon |
| `▼` | Dropdown |
| `●` | Selected state |
| `○` | Unselected state |

---

## AUTH-001 — SSO Login

**Route:** `/login`  **Guard:** none  **Width:** 480px centred card

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│                                                                  │
│              ┌────────────────────────────────┐                 │
│              │  {ContextIQ}                   │                 │
│              │  ContextIQ Platform            │                 │
│              │                                │                 │
│              │  Sign in to continue           │                 │
│              │                                │                 │
│              │  ┌──────────────────────────┐  │                 │
│              │  │  {SSO icon} Sign in with │  │                 │
│              │  │  Keycloak SSO            │  │                 │
│              │  └──────────────────────────┘  │                 │
│              │                                │                 │
│              │  ─────── or ────────           │                 │
│              │                                │                 │
│              │  Email   [________________]    │                 │
│              │  Password [_______________]    │                 │
│              │                                │                 │
│              │  [     Sign In     ]           │                 │
│              │                                │                 │
│              │  Forgot password?              │                 │
│              └────────────────────────────────┘                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Card | `<AuthCard>` | `elevation-2`, `radius-lg` | 480px max-width, centred vertically |
| SSO button | `<Button variant="outline">` | `brand-blue` border | Full-width, primary CTA |
| Email input | `<Input type="email">` | `neutral-100` bg | HTML `autocomplete="email"` |
| Password input | `<Input type="password">` | `neutral-100` bg | Toggle visibility icon |
| Sign In button | `<Button variant="primary">` | `brand-blue` fill | Submit, loading spinner on click |
| Background | — | `neutral-50` | Subtle grid pattern optional |

**States:** idle · loading (spinner on button) · error (inline field error) · SSO redirect

---

## SHELL-001 — App Shell

**Route:** all authenticated routes  **Guard:** any role

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR (full width · 56px)                                                    │
│ [≡] {ContextIQ} ContextIQ   /  Breadcrumb  /  Page Title   [🔍 Search ] [🔔][☀] │
├──────────────┬────────────────────────────────────────────────────────────────┤
│ SIDEBAR      │                                                                │
│ (220px)      │  MAIN CONTENT AREA (flex · 1 · padding 24px)                  │
│              │                                                                │
│ ⊞ Dashboard │                                                                │
│              │                                                                │
│ DATA SOURCES │                                                                │
│ ⬡ Connectors│                                                                │
│ 🗄 KnowSrc  │                                                                │
│              │                                                                │
│ GOVERNANCE   │                                                                │
│ 🛡 Policies │                                                                │
│              │                                                                │
│ OBSERVABILTY │                                                                │
│ ▶ Replay    │                                                                │
│ 📋 Audit Log│                                                                │
│ 📊 Observab.│                                                                │
│              │                                                                │
│ PLATFORM     │                                                                │
│ 👥 Users    │                                                                │
│ 💻 Models   │                                                                │
│ ⚙ Settings │                                                                │
│              │                                                                │
│ ─────────── │                                                                │
│ {avatar}    │                                                                │
│ admin        │                                                                │
│ ADMIN role   │                                                                │
└──────────────┴────────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Topbar | `<TopBar>` | `neutral-900` bg, `elevation-1` bottom shadow | `position: sticky; top: 0; z-index: 40` |
| Sidebar | `<SideNav>` | `neutral-850` bg | `position: sticky; top: 56px; height: calc(100vh - 56px); overflow-y: auto` |
| Nav section headers | `<NavSectionLabel>` | `neutral-400` text, `text-xs uppercase` | ARIA `role="group"` with label |
| Nav items | `<NavItem>` | `neutral-200` text, `brand-blue` active bg | `aria-current="page"` on active |
| User chip | `<UserChip>` | `neutral-700` bg | Avatar + name + role badge; clicking opens profile menu |
| Main content | `<main>` | `neutral-950` bg | `role="main"` landmark |
| Search | `<GlobalSearch>` | `neutral-800` bg | `⌘K` keyboard shortcut triggers it |
| Notification bell | `<NotificationBell>` | `neutral-200` icon | Badge count overlay |

**States:** nav collapsed (icon-only at `<= 1024px`) · section expanded/collapsed · active nav item · user menu open

---

## DASH-001 — Executive Overview Dashboard

**Route:** `/`  **Guard:** any role

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Dashboard                              [Export PDF]          │
│              │  ─────────────────────────────────────────────────────        │
│              │                                                               │
│              │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│              │  │Connectors│ │Active    │ │Audit     │ │Policy    │        │
│              │  │ ONLINE   │ │Policies  │ │Events    │ │PASS rate │        │
│              │  │  12 / 14 │ │    7     │ │   142    │ │   98.2%  │        │
│              │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────┐        │
│              │  │ Policy Decision Trend  (7-day line chart)        │        │
│              │  │                                                  │        │
│              │  │   ALLOW ●─────────────────────────────          │        │
│              │  │   DENY  ●──────────────────────────             │        │
│              │  │                        [7d] [30d] [90d]         │        │
│              │  └──────────────────────────────────────────────────┘        │
│              │                                                               │
│              │  ┌─────────────────────────┐  ┌───────────────────────────┐  │
│              │  │ Connector Health         │  │ Recent Audit Events        │  │
│              │  │ ● SQL-PROD    HEALTHY   │  │ POLICY_UPDATED  2m ago    │  │
│              │  │ ● REST-EXTAPI DEGRADED  │  │ CONNECTOR_EDIT  5m ago    │  │
│              │  │ ○ GRPC-ML     OFFLINE   │  │ USER_ROLE_CHG   12m ago   │  │
│              │  │ [View all connectors]   │  │ [View audit log]           │  │
│              │  └─────────────────────────┘  └───────────────────────────┘  │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Stat cards (×4) | `<StatCard>` | `neutral-850` bg, `radius-md` | Value, label, trend delta; responsive 4→2→1 col |
| Line chart | `<PolicyTrendChart>` | `brand-blue` / `red-500` strokes | Recharts; ARIA `role="img"` with description |
| Connector health list | `<ConnectorHealthList>` | `neutral-850` bg | StatusBadge + connector name |
| Audit feed | `<RecentAuditFeed>` | `neutral-850` bg | Top 5 events, relative timestamp |

**States:** loading skeletons · empty state (no data) · error banner

---

## CONN-001 — Connector List

**Route:** `/connectors`  **Guard:** PLATFORM_ENGINEER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Connectors                         [+ Add Connector]         │
│ (Connectors  │  ─────────────────────────────────────────────────────        │
│  active)     │  [🔍 Filter by name...] [Type ▼] [Status ▼]  14 connectors    │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ NAME ▲      TYPE       STATUS      LAST SYNC    ACTIONS│   │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ sql-prod    SQL DB     ● HEALTHY   2 min ago  [⋯]   │    │
│              │  │ rest-ext    REST API   ● HEALTHY   5 min ago  [⋯]   │    │
│              │  │ grpc-ml     gRPC       ▲ DEGRADED  12 min ago [⋯]   │    │
│              │  │ file-s3     File/S3    ✕ OFFLINE   1 hr ago   [⋯]   │    │
│              │  │ ...         ...        ...         ...        [⋯]   │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  Showing 1–20 of 14   [< Prev]  [Next >]                     │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Page header | `<PageHeader>` | — | Title + primary CTA button |
| Filter bar | `<FilterBar>` | `neutral-850` bg | Text search + type dropdown + status dropdown |
| Data table | `<DataTable>` | alternating `neutral-900`/`neutral-850` rows | Sortable columns; keyboard navigable |
| Status badge | `<StatusBadge>` | green/amber/red semantic tokens | HEALTHY · DEGRADED · OFFLINE |
| Row action menu | `<DropdownMenu>` | — | Edit · Test · Delete (ADMIN only) |
| Pagination | `<Pagination>` | — | Page-based; show total count |

**States:** loading (skeleton rows) · empty (no connectors: illustration + "Add your first connector" CTA) · filter no-results · error banner

---

## CONN-002 — Add / Edit Connector (Slide-over Drawer)

**Route:** triggers on `/connectors/new` or `/connectors/:id/edit`  **Width:** 480px right-anchored drawer

```
                              ┌────────────────────────────────────────────┐
                              │  [×]  Add Connector                         │
                              │  ─────────────────────────────────────────  │
                              │                                             │
                              │  Connector Name                            │
                              │  [________________________________]         │
                              │                                             │
                              │  Type                                       │
                              │  [SQL Database  ▼                ]          │
                              │                                             │
                              │  ── Connection Details ───────────────      │
                              │                                             │
                              │  Host          [____________________]       │
                              │  Port          [5432]                       │
                              │  Database      [____________________]       │
                              │  Username      [____________________]       │
                              │  Password      [••••••••••••••••]  [👁]    │
                              │  Schema        [public ▼          ]         │
                              │                                             │
                              │  ── Advanced ──────────────────────         │
                              │  ▶ SSL / TLS settings                       │
                              │  ▶ Connection pooling                       │
                              │                                             │
                              │  [  Test Connection  ]                      │
                              │  ✓ Connection OK  (green badge)             │
                              │                                             │
                              │  ─────────────────────────────────────────  │
                              │  [Cancel]              [Save Connector]    │
                              └────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Drawer | `<SlideOverDrawer>` | `neutral-900` bg, `elevation-3` left shadow | `role="dialog"` · focus trap · `Escape` closes |
| Type selector | `<Select>` | — | Options: SQL DB · REST API · gRPC · File/S3 |
| Dynamic fields | conditional render per type | — | SQL shows host/port/db; REST shows base-URL + auth scheme |
| Password input | `<PasswordInput>` | — | Toggle visibility; never echoed to logs |
| Accordion (Advanced) | `<Accordion>` | — | Collapsed by default |
| Test button | `<Button variant="outline">` | — | Fires POST /connectors/test; shows inline result badge |
| Save button | `<Button variant="primary">` | `brand-blue` | Disabled until test passes OR user explicitly overrides |

**States:** idle · testing (spinner) · test OK · test FAIL · saving · saved · validation errors per field

---

## CONN-003 — Connector Health Detail

**Route:** `/connectors/:id`  **Guard:** PLATFORM_ENGINEER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Connectors  /  sql-prod              [Edit] [Test] [Delete]  │
│              │  ─────────────────────────────────────────────────────        │
│              │  ● HEALTHY   SQL Database   Last sync: 2 min ago              │
│              │                                                               │
│              │  ┌─────────────────────────────┐  ┌──────────────────────┐   │
│              │  │ Connection Info              │  │ Health History       │   │
│              │  │ Host:  db.internal:5432      │  │ (sparkline 24h)      │   │
│              │  │ DB:    contextiq_prod        │  │  ─────────────────   │   │
│              │  │ Schema: public               │  │  uptime 99.8%        │   │
│              │  │ SSL:    ✓ enabled            │  └──────────────────────┘   │
│              │  └─────────────────────────────┘                             │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ Probe Log                              [Refresh]      │    │
│              │  │ 14:32:01 ● HEALTHY   latency 4ms                     │    │
│              │  │ 14:27:01 ● HEALTHY   latency 3ms                     │    │
│              │  │ 14:22:01 ▲ DEGRADED  latency 312ms  (timeout)        │    │
│              │  │ ...                                                   │    │
│              │  └──────────────────────────────────────────────────────┘    │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Status hero | `<ConnectorStatusHero>` | semantic color band | Large status badge + last-sync time |
| Info card | `<DefinitionList>` | `neutral-850` | Key-value pairs for connection metadata |
| Health sparkline | `<HealthSparkline>` | green/red line | 24-hour availability; hover shows timestamp |
| Probe log table | `<ProbeLogTable>` | monospace `IBM Plex Mono` timestamps | Auto-refreshes every 30s |

---

## KS-001 — Knowledge Sources

**Route:** `/knowledge-sources`  **Guard:** PLATFORM_ENGINEER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Knowledge Sources                [+ Add Knowledge Source]    │
│              │  ─────────────────────────────────────────────────────        │
│              │  [🔍 Filter...]  [Type ▼]  [Status ▼]                         │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ NAME         TYPE      STATUS    DOCS     LAST INDEX  │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ prod-docs    Markdown  ● SYNCED  1,204    10 min ago  │    │
│              │  │ api-spec     OpenAPI   ● SYNCED    48     1 hr ago    │    │
│              │  │ wiki-conf    Confluence▲ STALE     892    2 days ago  │    │
│              │  └──────────────────────────────────────────────────────┘    │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Table | `<DataTable>` | — | Columns: name, type, status, doc count, last index |
| Status | `<StatusBadge>` | green=SYNCED, amber=STALE, red=ERROR | — |

---

## KS-002 — Add / Edit Knowledge Source (Drawer)

**Route:** `/knowledge-sources/new`  **Width:** 480px right-anchored drawer

```
                              ┌────────────────────────────────────────────┐
                              │  [×]  Add Knowledge Source                  │
                              │  ─────────────────────────────────────────  │
                              │  Name     [________________________________] │
                              │  Type     [Markdown ▼                     ] │
                              │                                             │
                              │  Source Path / URL                          │
                              │  [________________________________]         │
                              │                                             │
                              │  Sync Schedule  [Every 6 hours ▼         ] │
                              │                                             │
                              │  Embedding Model [text-embedding-3-s ▼  ]  │
                              │                                             │
                              │  [Cancel]              [Save Source]       │
                              └────────────────────────────────────────────┘
```

---

## POL-001 — Policy List

**Route:** `/policies`  **Guard:** SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Policies                               [+ New Policy]        │
│              │  ─────────────────────────────────────────────────────        │
│              │  [🔍 Filter...]  [Status ▼]  [Scope ▼]                        │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ ○  NAME              SCOPE      STATUS   UPDATED     │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ ○  pii-redaction     global     ● Active  today      │    │
│              │  │ ●  rate-limiter      connector  ○ Draft   yesterday  │    │
│              │  │ ○  output-filter     model      ● Active  3 days ago │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  [Activate Selected] [Deactivate Selected] [Delete Selected]  │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Row checkbox | `<Checkbox>` | — | Enables bulk actions |
| Status badge | `<StatusBadge>` | green=Active, neutral=Draft | — |
| Bulk action bar | `<BulkActionBar>` | `brand-blue` bg | Appears when ≥1 row selected; `position: sticky; bottom: 0` |

---

## POL-002 — Policy Editor

**Route:** `/policies/new`, `/policies/:id`  **Guard:** SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Policies  /  pii-redaction                                   │
│              │  ─────────────────────────────────────────────────────        │
│              │  Name  [pii-redaction___________]  Scope [global ▼]  ● Active │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────┬──────────┐ │
│              │  │ 1  package contextiq.policies                │ ERRORS 0 │ │
│              │  │ 2                                            │          │ │
│              │  │ 3  default allow = false                     │ WARNINGS │ │
│              │  │ 4                                            │ ▲ line 7 │ │
│              │  │ 5  allow {                                   │ unused   │ │
│              │  │ 6    not contains(input.text, "SSN")         │ var      │ │
│              │  │ 7    not contains(input.text, "DOB")         │          │ │
│              │  │ 8  }                                         │          │ │
│              │  │ 9                                            │          │ │
│              │  │ ...                                          │          │ │
│              │  └──────────────────────────────────────────────┴──────────┘ │
│              │                 Monaco Editor · Rego syntax                   │
│              │                                                               │
│              │  [Test in Simulation]    [Save Draft]    [Activate]           │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Monaco editor | `<MonacoEditor language="rego">` | `neutral-950` bg, `IBM Plex Mono` | Real-time linting via OPA WASM; gutter markers |
| Lint panel | `<LintPanel>` | `neutral-900` bg | List of errors/warnings with click-to-navigate |
| Name input | `<Input>` | — | Inline editable in header |
| Scope selector | `<Select>` | — | global · connector · model |
| Status toggle | `<Badge>` + `<Switch>` | — | Click to activate/deactivate with confirmation |
| Footer actions | `<ButtonGroup>` | — | Test · Save Draft · Activate; sticky at editor bottom |

**States:** new (blank) · editing · linting (debounce indicator) · lint error · save in-progress · saved · activated

---

## POL-003 — Policy Simulation

**Route:** `/policies/:id/simulate`  **Guard:** SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Policies  /  pii-redaction  /  Simulate       [← Back]       │
│              │  ─────────────────────────────────────────────────────        │
│              │  ┌─────────────────────────┐  ┌──────────────────────────┐   │
│              │  │ Input Payload           │  │ Decision Result          │   │
│              │  │ (JSON editor)           │  │                          │   │
│              │  │                         │  │  ╔═══════════════════╗   │   │
│              │  │ {                       │  │  ║  DENY             ║   │   │
│              │  │   "text": "SSN: 123...",│  │  ╚═══════════════════╝   │   │
│              │  │   "model": "gpt-4o",   │  │                          │   │
│              │  │   "context": {...}      │  │  Matched rule:           │   │
│              │  │ }                       │  │  allow { ... }  line 5   │   │
│              │  │                         │  │                          │   │
│              │  │                         │  │  Binding path:           │   │
│              │  │              [Run ▶]   │  │  input.text ⊇ "SSN"     │   │
│              │  └─────────────────────────┘  └──────────────────────────┘   │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Input editor | `<MonacoEditor language="json">` | `neutral-950` | Sample payload preloaded from last trace |
| Run button | `<Button variant="primary">` | `brand-blue` | Fires POST /policies/:id/simulate |
| Decision badge | `<DecisionBadge>` | red=DENY, green=ALLOW | Prominent, centred |
| Binding path | `<CodeBlock>` | `IBM Plex Mono` | Shows which rule triggered |

---

## REPLAY-001 — Trace List (Replay Explorer)

**Route:** `/traces`  **Guard:** AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Replay Explorer                                              │
│              │  ─────────────────────────────────────────────────────        │
│              │  [🔍 Session ID / trace ID...]  [Model ▼] [Status ▼] [Date ▼] │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ TRACE ID       STATUS    MODEL      PHASES  STARTED  │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ trace-abc-001  ✓ PASS    gpt-4o     5       2m ago   │    │
│              │  │ trace-abc-002  ✗ DENIED  gpt-4o     3       5m ago   │    │
│              │  │ trace-abc-003  ✓ PASS    claude-3   5       12m ago  │    │
│              │  │ trace-abc-004  ⚠ WARN    llama3     4       1h ago   │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  [Load more]  (cursor-paginated infinite scroll)              │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

---

## REPLAY-002 — Trace Timeline

**Route:** `/traces/:id`  **Guard:** AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Traces  /  trace-abc-002           ✗ DENIED    [Export JSON] │
│              │  ─────────────────────────────────────────────────────        │
│              │  Model: gpt-4o  ·  Session: sess-xyz  ·  Duration: 1.24s      │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ PHASE TIMELINE                     0ms      1240ms   │    │
│              │  │                                    │            │     │    │
│              │  │ PLAN        ████████               │──────▓▓▓▓▓│     │    │
│              │  │ RETRIEVE    ████████████████       │──────────▓│     │    │
│              │  │ REASON      ████████████           │─────────▓▓│     │    │
│              │  │ GENERATE    ████████████████████   │──────────▓│ ◄── DENY │
│              │  │ EVAL        ██                     │──▓│        │     │    │
│              │  │                                                       │    │
│              │  │  Click any phase segment to open detail drawer        │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  ┌────────────────────────────────────────────────────────┐   │
│              │  │ PHASE SUMMARY                                          │   │
│              │  │ Phase    Latency  Tokens In  Tokens Out  Policy Result │   │
│              │  │ PLAN       42ms       128         64     ALLOW         │   │
│              │  │ RETRIEVE  310ms       512        256     ALLOW         │   │
│              │  │ REASON    280ms       768        384     ALLOW         │   │
│              │  │ GENERATE  594ms      1024        512     DENY ✗        │   │
│              │  │ EVAL       14ms        32         16     ALLOW         │   │
│              │  └────────────────────────────────────────────────────────┘   │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Timeline chart | `<PhaseTimeline>` | `brand-blue` bars, `red-500` on DENY phase | Horizontal Gantt; click-to-open drawer |
| Phase summary | `<PhaseTable>` | `neutral-850` | Sortable by latency |
| Status hero | `<TraceStatusHero>` | red=DENIED, green=PASS, amber=WARN | Sticky sub-header |

---

## REPLAY-003 — Phase Detail Drawer

**Route:** none (drawer over REPLAY-002)  **Width:** 480px

```
                              ┌────────────────────────────────────────────┐
                              │  [×]  GENERATE Phase Detail                 │
                              │  ─────────────────────────────────────────  │
                              │  Status: DENY ✗   Latency: 594ms            │
                              │                                             │
                              │  Policy Decision                            │
                              │  ┌──────────────────────────────────────┐  │
                              │  │ DENY — pii-redaction policy          │  │
                              │  │ Matched: input.text ⊇ "SSN"         │  │
                              │  └──────────────────────────────────────┘  │
                              │                                             │
                              │  Input (truncated)                          │
                              │  ┌──────────────────────────────────────┐  │
                              │  │ {                                    │  │
                              │  │   "prompt": "...[1024 tokens]...",   │  │
                              │  │   "context_window": 4096             │  │
                              │  │ }                              [Copy]│  │
                              │  └──────────────────────────────────────┘  │
                              │                                             │
                              │  Output                                     │
                              │  ┌──────────────────────────────────────┐  │
                              │  │  [BLOCKED — policy denied output]    │  │
                              │  └──────────────────────────────────────┘  │
                              │                                             │
                              │  Embedding Vector (first 8 dims)           │
                              │  [0.12, -0.33, 0.07, 0.91, ...]   [Copy]  │
                              └────────────────────────────────────────────┘
```

---

## AUDIT-001 — Audit Log

**Route:** `/audit-log`  **Guard:** AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Audit Log                      [Verify Integrity] [Export]   │
│              │  ─────────────────────────────────────────────────────        │
│              │  [Action ▼] [Resource ▼] [Actor email...] [From date] [To]   │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ TIMESTAMP           ACTION           ACTOR           │    │
│              │  │                     RESOURCE         RESOURCE ID     │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ ▶ 2026-07-14 14:32  POLICY_UPDATED   alice@co.com    │    │
│              │  │   POLICY            pol-abc-001                      │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ ▼ 2026-07-14 14:28  CONNECTOR_EDITED  bob@co.com     │    │
│              │  │   CONNECTOR         conn-sql-001                     │    │
│              │  │   ┌───────────────────────────────────────────────┐  │    │
│              │  │   │ before: { "host": "old.db" }                  │  │    │
│              │  │   │ after:  { "host": "new.db" }                  │  │    │
│              │  │   └───────────────────────────────────────────────┘  │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ ▶ 2026-07-14 14:15  USER_ROLE_CHANGED carol@co.com  │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  [Load more]  (cursor-paginated)                             │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Filter bar | `<AuditLogFilterBar>` | `neutral-850` bg | RHF + Zod validation |
| Table rows | `<AuditLogTable>` | alternating rows | `▶` = collapsed, `▼` = expanded diff |
| Diff viewer | `<JsonDiffViewer>` | `neutral-900` bg, `IBM Plex Mono` | before/after highlighted diff |
| Verify button | `<Button variant="outline">` | `brand-blue` | Links to AUDIT-002 |
| Load more | `<Button variant="ghost">` | — | Fires `fetchNextPage` via TanStack Query |

**States:** loading (skeleton) · empty (no events) · expanded row · filter active

---

## AUDIT-002 — Chain Integrity Verification

**Route:** `/audit-log/verify`  **Guard:** AUDITOR, SECURITY_OFFICER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Audit Log  /  Chain Integrity                                │
│              │  ─────────────────────────────────────────────────────        │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │                                                      │    │
│              │  │  Audit chain integrity verification recomputes the   │    │
│              │  │  SHA-256 hash chain across all audit log entries and │    │
│              │  │  confirms no row has been tampered with or deleted.  │    │
│              │  │                                                      │    │
│              │  │  Last verified:  Never                               │    │
│              │  │  Rows in chain:  1,204                               │    │
│              │  │                                                      │    │
│              │  │              [  Run Verification  ]                  │    │
│              │  │                                                      │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │  ●  RESULT (after running)                           │    │
│              │  │                                                      │    │
│              │  │  ╔══════════════════════════════════════════════╗   │    │
│              │  │  ║  Chain Valid ✓  — 1,204 rows verified        ║   │    │
│              │  │  ╚══════════════════════════════════════════════╝   │    │
│              │  │                                                      │    │
│              │  │  Verified at: 2026-07-14 14:45:01 UTC               │    │
│              │  └──────────────────────────────────────────────────────┘    │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Info card | `<InfoCard>` | `neutral-850` | Description + last-verified time + row count |
| Run button | `<Button variant="primary">` | `brand-blue` | Fires GET /audit-log/verify; shows spinner during |
| Result card (VALID) | `<IntegrityResultCard variant="success">` | `success-900` bg | Green border + checkmark |
| Result card (TAMPERED) | `<IntegrityResultCard variant="error">` | `error-900` bg | First divergent row + hash mismatch |
| Evidence download | `<Button variant="outline">` | `red-500` | Appears only on TAMPERED result |

**States:** idle (no result) · loading · valid · tampered (with evidence panel)

---

## USER-001 — User Management

**Route:** `/users`  **Guard:** ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Users                                    [+ Invite User]     │
│              │  ─────────────────────────────────────────────────────        │
│              │  [🔍 Filter by name / email...]  [Role ▼]                     │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ AVATAR  NAME              EMAIL           ROLE        │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ [AA]    Alice Admin        alice@co.com   ADMIN       │    │
│              │  │ [BP]    Bob PE             bob@co.com     PLATFORM_ENG│    │
│              │  │ [CS]    Carol Sec          carol@co.com   SEC_OFFICER │    │
│              │  └──────────────────────────────────────────────────────┘    │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

---

## USER-002 — Role Assignment (Drawer)

**Route:** triggers from USER-001 row click  **Width:** 360px

```
                              ┌────────────────────────────────────────────┐
                              │  [×]  Bob PE — Role Assignment              │
                              │  ─────────────────────────────────────────  │
                              │                                             │
                              │  {avatar}  Bob PE                           │
                              │            bob@co.com                       │
                              │                                             │
                              │  Assigned Role                              │
                              │  ┌──────────────────────────────────────┐  │
                              │  │ PLATFORM_ENGINEER               [▼] │  │
                              │  └──────────────────────────────────────┘  │
                              │                                             │
                              │  Role grants access to:                    │
                              │  ✓ Connectors                              │
                              │  ✓ Knowledge Sources                       │
                              │  ✓ Models                                  │
                              │  ✕ Policies (requires SEC_OFFICER)         │
                              │  ✕ Users (requires ADMIN)                  │
                              │                                             │
                              │  [Cancel]              [Save Role]         │
                              └────────────────────────────────────────────┘
```

---

## MODEL-001 — Model Registry

**Route:** `/models`  **Guard:** PLATFORM_ENGINEER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Models                          [+ Add Model] [Routing Wts]  │
│              │  ─────────────────────────────────────────────────────        │
│              │  [🔍 Filter...]  [Provider ▼]  [Status ▼]                     │
│              │                                                               │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │ NAME          PROVIDER   CONTEXT   STATUS   WEIGHT   │    │
│              │  ├──────────────────────────────────────────────────────┤    │
│              │  │ gpt-4o        OpenAI     128k      ● Active   60%    │    │
│              │  │ claude-3-s    Anthropic   200k      ● Active   30%    │    │
│              │  │ llama3-70b    Local       8k        ○ Inactive  10%   │    │
│              │  └──────────────────────────────────────────────────────┘    │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

---

## MODEL-002 — Add / Edit Model (Drawer)

**Route:** `/models/add`  **Width:** 480px

```
                              ┌────────────────────────────────────────────┐
                              │  [×]  Add Model                             │
                              │  ─────────────────────────────────────────  │
                              │  Display Name  [____________________]       │
                              │  Provider      [OpenAI ▼            ]       │
                              │  Model ID      [gpt-4o_______________]       │
                              │  API Endpoint  [https://api.openai..]        │
                              │  API Key       [••••••••••••••••]  [👁]    │
                              │  Context Limit [128000______________]        │
                              │                                             │
                              │  Initial routing weight: [50]%             │
                              │                                             │
                              │  [Cancel]              [Save Model]        │
                              └────────────────────────────────────────────┘
```

---

## MODEL-003 — Routing Weights

**Route:** `/models/weights`  **Guard:** PLATFORM_ENGINEER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Models  /  Routing Weights                   [Save Weights]  │
│              │  ─────────────────────────────────────────────────────        │
│              │  Total must equal 100%.  Current: 100%  ✓                     │
│              │                                                               │
│              │  gpt-4o (OpenAI)                                              │
│              │  ████████████████████████████████████████████████  60%       │
│              │  [────────────────────────────────────────────────────]       │
│              │                                                               │
│              │  claude-3-s (Anthropic)                                       │
│              │  ████████████████████  30%                                    │
│              │  [────────────────────────────────────────────────────]       │
│              │                                                               │
│              │  llama3-70b (Local)                                           │
│              │  ███████  10%                                                 │
│              │  [────────────────────────────────────────────────────]       │
│              │                                                               │
│              │  ⚠  Weights must sum to 100%  (shown when they don't)        │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Weight sliders | `<WeightSlider>` | `brand-blue` track fill | Dragging one redistributes others proportionally |
| Total indicator | `<WeightTotal>` | green=100%, red=not 100% | `aria-live="polite"` for screen reader updates |
| Save button | `<Button variant="primary">` | Disabled until total === 100% | — |

---

## OBS-001 — Observability Dashboard

**Route:** `/observability`  **Guard:** DEVOPS_SRE, MANAGER, ADMIN

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │  Observability                            [Last 1h ▼] [🔄]   │
│              │  ─────────────────────────────────────────────────────        │
│              │  [Latency] [Throughput] [Errors] [Token Usage] [Cost]         │
│              │  ─────────────────────────────────────────────────────        │
│              │  ┌──────────────────────────────────────────────────────┐    │
│              │  │  p50: 210ms   p95: 890ms   p99: 1,420ms             │    │
│              │  │                                                      │    │
│              │  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ (p95 line chart)  │    │
│              │  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ (p50 line chart)  │    │
│              │  │                                                      │    │
│              │  │  [1h] [6h] [24h] [7d]                               │    │
│              │  └──────────────────────────────────────────────────────┘    │
│              │                                                               │
│              │  ┌──────────────────────────┐  ┌──────────────────────────┐  │
│              │  │ Top Models by Latency    │  │ Error Rate (%)           │  │
│              │  │ gpt-4o     890ms avg     │  │ ████  2.1% last 1h       │  │
│              │  │ claude-3s  620ms avg     │  │                          │  │
│              │  └──────────────────────────┘  └──────────────────────────┘  │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

| Zone | Component | Token | Notes |
|---|---|---|---|
| Tab bar | `<TabBar>` | `brand-blue` active underline | Keyboard navigable, `role="tablist"` |
| Line chart | `<LatencyChart>` | `brand-blue`/`amber-500` percentile lines | Recharts; tooltip on hover |
| Stat cards | `<StatCard>` | — | p50 / p95 / p99 |
| Time range selector | `<TimeRangeSelect>` | — | 1h / 6h / 24h / 7d; stale indicator on old data |

---

## ERR-001 — Access Denied

**Route:** `/403`  **Guard:** any authenticated

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR                                                                       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ SIDEBAR      │                                                               │
│              │                                                               │
│              │                  {lock icon (48px)}                           │
│              │                                                               │
│              │               Access Denied                                   │
│              │                                                               │
│              │       You don't have permission to view this page.            │
│              │       Contact your administrator to request access.           │
│              │                                                               │
│              │            [← Back]    [Go to Dashboard]                      │
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

---

## ERR-002 — Unauthenticated Redirect

**Route:** any protected route when session is missing/expired  **Behaviour:** redirect only (no screen rendered)

Middleware redirects `→ /login?returnTo=<encoded_original_path>`. After successful login, SSO callback restores `returnTo`.

---

## Responsive Behaviour Summary

| Breakpoint | Sidebar | Content Columns | Notes |
|---|---|---|---|
| `2xl` (≥ 1536px) | 220px fixed | 4 columns | Full desktop |
| `xl` (≥ 1280px) | 220px fixed | 4 columns | **Design target** |
| `lg` (≥ 1024px) | Icon-only (48px) | 3 columns | Sidebar collapse to icon-only |
| `md` (≥ 768px) | Hidden (hamburger) | 2 columns | Mobile-first tablet |
| `sm` (≥ 640px) | Hidden (hamburger) | 1 column | Phone |
| `xs` (< 640px) | Hidden (hamburger) | 1 column | Small phone |

*At `lg` and below, the sidebar collapses to icon-only mode. At `md` and below, a hamburger button appears in the topbar that opens the full sidebar as a modal drawer.*

---

*Source: `figma_spec_contextiq.md` Parts 4, 5, 6 — Responsive Breakpoints, Screen Inventory, Component Inventory*
