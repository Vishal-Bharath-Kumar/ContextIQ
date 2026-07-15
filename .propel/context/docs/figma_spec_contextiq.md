# ContextIQ — Figma UX Specification

## Metadata

| Field | Value |
|---|---|
| Project | ContextIQ |
| Document Type | Figma Screen Specification |
| Version | 1.0 |
| Status | Draft |
| Author | GitHub Copilot (generated from spec.md v1.0) |
| Sources | `.propel/context/docs/spec.md` |
| Date | 2026-07-14 |

---

## Part 1 — Aesthetic Direction

### Direction Output

```
Direction:  utilitarian

Rationale:  ContextIQ serves technically expert users — platform engineers,
            auditors, DevOps/SRE engineers, security officers — performing
            high-stakes, data-intensive administrative tasks: policy authoring,
            trace replay, connector health, and audit log review. The required
            emotional register is rigorous and calm. Decorative animation or
            expressive typography would undermine trust and distract from
            information. Utilitarian matches exactly: density is the feature,
            not the obstacle. Every pixel earns its place. Keyboard-first
            workflows align with the SRE persona for whom mouse interaction
            is the degraded path.

Precedents: Grafana (dense dashboard composition, semantic color for status),
            Sentry (error inspection drill-down, monospace data, tight spacing),
            PostHog (event stream analysis, tabular numerals, terse labeling)

Anti-brief: Must not resemble AI-assistant marketing pages (purple-to-blue
            gradients, hero animations, glassmorphism). Must not resemble
            Bootstrap admin templates (thick colored-border alerts, rainbow
            sidebar icons, excessive card drop-shadows). Must not resemble
            Notion or Linear (whitespace as brand signal — ContextIQ's value
            IS density, not breathing room).
```

---

## Part 2 — Design Token System

### 2.1 Color — OKLCH Primitive Palette

All values in `oklch(L C H)`. Consumers reference semantic tokens only; hex literals appear only in this table.

#### Brand Blue (anchor hue H=260 — enterprise blue-violet)

| Token | OKLCH | Hex (reference) |
|---|---|---|
| `brand-blue-50` | `oklch(0.98 0.008 260)` | `#f4f4fb` |
| `brand-blue-100` | `oklch(0.95 0.018 260)` | `#eaebf7` |
| `brand-blue-200` | `oklch(0.90 0.035 260)` | `#d5d6f2` |
| `brand-blue-300` | `oklch(0.82 0.070 260)` | `#b3b5e8` |
| `brand-blue-400` | `oklch(0.65 0.130 260)` | `#7b7fd6` |
| `brand-blue-500` | `oklch(0.50 0.185 260)` | `#4950c2` |
| `brand-blue-600` | `oklch(0.43 0.175 260)` | `#3940ae` |
| `brand-blue-700` | `oklch(0.36 0.155 260)` | `#2d3494` |
| `brand-blue-800` | `oklch(0.28 0.120 260)` | `#1f2470` |
| `brand-blue-900` | `oklch(0.20 0.085 260)` | `#141850` |
| `brand-blue-950` | `oklch(0.14 0.055 260)` | `#0c1038` |

#### Neutral (brand-tinted chroma 0.012–0.015, H=260)

| Token | OKLCH | Hex (reference) |
|---|---|---|
| `neutral-0` | `oklch(0.99 0.005 260)` | `#fafafd` |
| `neutral-50` | `oklch(0.97 0.010 260)` | `#f2f2f9` |
| `neutral-100` | `oklch(0.94 0.015 260)` | `#e8e8f3` |
| `neutral-200` | `oklch(0.89 0.015 260)` | `#dcdcec` |
| `neutral-300` | `oklch(0.78 0.015 260)` | `#c4c4de` |
| `neutral-400` | `oklch(0.64 0.015 260)` | `#9e9eb8` |
| `neutral-500` | `oklch(0.50 0.015 260)` | `#75758e` |
| `neutral-600` | `oklch(0.40 0.015 260)` | `#5c5c73` |
| `neutral-700` | `oklch(0.32 0.015 260)` | `#44445c` |
| `neutral-800` | `oklch(0.22 0.015 260)` | `#2c2c42` |
| `neutral-900` | `oklch(0.15 0.015 260)` | `#1a1a2e` |
| `neutral-950` | `oklch(0.10 0.010 260)` | `#11111e` |

#### Semantic Accent Primitives

| Token | OKLCH | Semantic |
|---|---|---|
| `success-400` | `oklch(0.72 0.17 145)` | success text (dark mode) |
| `success-600` | `oklch(0.55 0.17 145)` | success text (light mode) |
| `success-50` | `oklch(0.97 0.05 145)` | success surface |
| `warning-400` | `oklch(0.78 0.17 65)` | warning text (dark mode) |
| `warning-600` | `oklch(0.55 0.17 65)` | warning text (light mode) |
| `warning-50` | `oklch(0.97 0.05 65)` | warning surface |
| `danger-400` | `oklch(0.65 0.22 25)` | danger text (dark mode) |
| `danger-600` | `oklch(0.50 0.22 25)` | danger text (light mode) |
| `danger-50` | `oklch(0.97 0.05 25)` | danger surface |
| `info-400` | `oklch(0.68 0.13 200)` | info text (dark mode) |
| `info-600` | `oklch(0.48 0.13 200)` | info text (light mode) |
| `info-50` | `oklch(0.97 0.04 200)` | info surface |

### 2.2 Color — Semantic Token Map

#### Light Mode

| Token | Resolves to | Usage |
|---|---|---|
| `text-primary` | `neutral-900` | Body text, headings |
| `text-secondary` | `neutral-600` | Captions, labels, secondary content |
| `text-muted` | `neutral-400` | Placeholders, hints, disabled labels |
| `text-on-accent` | `neutral-0` | Text on filled buttons, badges |
| `text-danger` | `danger-600` | Inline error messages |
| `text-success` | `success-600` | Inline success messages |
| `text-warning` | `warning-600` | Inline warning messages |
| `text-link` | `brand-blue-600` | Interactive links |
| `surface-canvas` | `neutral-0` | Page background |
| `surface-raised` | `neutral-50` | Cards, table rows (hover) |
| `surface-sunken` | `neutral-100` | Table header, sidebar background |
| `surface-accent` | `brand-blue-50` | Selected nav item background |
| `surface-danger` | `danger-50` | Error state backgrounds |
| `surface-success` | `success-50` | Success state backgrounds |
| `surface-warning` | `warning-50` | Warning state backgrounds |
| `surface-info` | `info-50` | Info state backgrounds |
| `border-subtle` | `neutral-200` | Default card, input borders |
| `border-strong` | `neutral-300` | Dividers, table separators |
| `border-focus` | `brand-blue-500` | Keyboard focus rings |
| `feedback-danger` | `danger-600` | Alert / toast text |
| `feedback-success` | `success-600` | Alert / toast text |
| `feedback-warning` | `warning-600` | Alert / toast text |
| `feedback-info` | `info-600` | Alert / toast text |
| `action-primary` | `brand-blue-600` | Primary button fill |
| `action-primary-hover` | `brand-blue-700` | Primary button hover |
| `action-primary-active` | `brand-blue-800` | Primary button pressed |
| `action-primary-disabled` | `neutral-300` | Primary button disabled fill |
| `action-secondary` | `neutral-100` | Secondary button fill |
| `action-secondary-hover` | `neutral-200` | Secondary button hover |
| `action-danger` | `danger-600` | Destructive action fill |
| `action-danger-hover` | `danger-700` | Destructive action hover |

#### Dark Mode (separate resolution — not a color flip)

| Token | Resolves to |
|---|---|
| `text-primary` | `neutral-50` |
| `text-secondary` | `neutral-400` |
| `text-muted` | `neutral-600` |
| `text-link` | `brand-blue-400` |
| `surface-canvas` | `neutral-950` |
| `surface-raised` | `neutral-900` |
| `surface-sunken` | `oklch(0.08 0.008 260)` |
| `surface-accent` | `brand-blue-900` |
| `border-subtle` | `neutral-800` |
| `border-strong` | `neutral-700` |
| `border-focus` | `brand-blue-400` |
| `action-primary` | `brand-blue-400` |
| `action-primary-hover` | `brand-blue-300` |
| `action-primary-active` | `brand-blue-200` |
| `action-primary-disabled` | `neutral-700` |

### 2.3 Typography System

**Display family:** IBM Plex Sans  
**Body family:** IBM Plex Sans  
**Mono family:** IBM Plex Mono  
**Scale ratio:** 1.125 (major second) — tight, newspaper-like; optimal for dense admin tool  
**Anchor:** 1rem = 16px

| Token | rem | px | Weight | Family | Line-height | Usage |
|---|---|---|---|---|---|---|
| `type-caption` | 0.694 | 11 | 400 | IBM Plex Sans | 1.50 | Labels, counts, metadata |
| `type-small` | 0.778 | 12 | 400 | IBM Plex Sans | 1.50 | Secondary captions, badges |
| `type-body` | 1.000 | 16 | 400 | IBM Plex Sans | 1.55 | Default prose |
| `type-body-md` | 1.000 | 16 | 500 | IBM Plex Sans | 1.55 | Form labels, nav items |
| `type-lead` | 1.125 | 18 | 400 | IBM Plex Sans | 1.55 | Intro text, descriptions |
| `type-h5` | 1.266 | 20 | 600 | IBM Plex Sans | 1.35 | Card headings, section titles |
| `type-h4` | 1.424 | 23 | 600 | IBM Plex Sans | 1.30 | Modal headings |
| `type-h3` | 1.602 | 26 | 600 | IBM Plex Sans | 1.25 | Page sub-section headings |
| `type-h2` | 1.802 | 29 | 600 | IBM Plex Sans | 1.20 | Page headings |
| `type-h1` | 2.027 | 32 | 600 | IBM Plex Sans | 1.15 | Primary page title |
| `type-display` | 2.281 | 36 | 600 | IBM Plex Sans | 1.10 | Dashboard hero stats |
| `type-mono-sm` | 0.778 | 12 | 400 | IBM Plex Mono | 1.50 | IDs, hashes, short codes |
| `type-mono` | 1.000 | 16 | 400 | IBM Plex Mono | 1.50 | Code blocks, policy editor |
| `type-mono-lg` | 1.125 | 18 | 400 | IBM Plex Mono | 1.50 | Trace timeline timestamps |

**Tabular numerals:** `font-variant-numeric: tabular-nums` applied to all table cells, stat counters, and dashboard metrics.

### 2.4 Spacing, Radius, and Elevation

#### Spacing (4pt base)

| Token | Value | Usage |
|---|---|---|
| `space-1` | 4px | Icon-to-label gap, tag padding |
| `space-2` | 8px | Inline item gap, input padding (vertical) |
| `space-3` | 12px | Dense list item padding |
| `space-4` | 16px | Default component padding, gap between form fields |
| `space-5` | 20px | Card padding (compact) |
| `space-6` | 24px | Card padding (standard) |
| `space-8` | 32px | Section gap within page |
| `space-10` | 40px | Section gap (large breakpoint) |
| `space-12` | 48px | Page top padding |
| `space-16` | 64px | Page section breaks |

#### Radius Scale

| Token | Value | Usage |
|---|---|---|
| `r-none` | 0px | Table cells, code blocks |
| `r-xs` | 2px | Inline badges, status pips |
| `r-sm` | 4px | Buttons, inputs, chips |
| `r-md` | 6px | Dropdowns, panel borders |
| `r-lg` | 8px | Cards, modals |
| `r-xl` | 12px | Full-width banners |
| `r-full` | 9999px | Pill badges, avatar rings |

#### Elevation (three levels only)

| Level | CSS value | Usage |
|---|---|---|
| resting | `box-shadow: 0 1px 2px oklch(0 0 0 / 0.08)` | Default cards, table wrappers |
| raised | `box-shadow: 0 4px 8px oklch(0 0 0 / 0.10), 0 1px 2px oklch(0 0 0 / 0.08)` | Dropdowns, hover cards |
| floating | `box-shadow: 0 8px 24px oklch(0 0 0 / 0.14), 0 2px 6px oklch(0 0 0 / 0.10)` | Modals, command palette |

---

## Part 3 — Motion Personality

```
motion_personality:

  Direction:  utilitarian — motion is diagnostic, never decorative.

  Easing curves:
    standard:    cubic-bezier(0.4, 0, 0.2, 1)   — state feedback, color transitions
    entry:       cubic-bezier(0, 0, 0.2, 1)      — modal / drawer enter only
    exit:        cubic-bezier(0.4, 0, 1, 1)      — modal / drawer leave only
    emphasized:  NOT USED — direction prohibits flourish

  Timing windows:
    micro:       80–120ms  — button press, toggle, focus ring
    standard:    150–200ms — dropdown open, toast enter
    emphasized:  250–300ms — modal enter, drawer slide (only)

  Rules:
    - Animate transform + opacity only; never layout properties.
    - No decorative hover animations.
    - No scroll-linked effects or parallax.
    - No page-load ceremonies > 200ms total.
    - Skeleton loaders (opacity pulse 1.0→0.4, 1200ms, ease-in-out) for
      async content boundaries; no spinners for inline async.
    - Toast notifications: slide-in from top-right, 150ms entry; auto-dismiss
      after 4000ms with 150ms exit.

  Reduced motion:
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
      }
    }
    /* Exception: opacity cross-fades for state legibility ≤ 80ms */
```

---

## Part 4 — Responsive Breakpoints

| Breakpoint | Min-width | Layout |
|---|---|---|
| `xs` | 0px | Mobile (admin portal: read-only view only) |
| `sm` | 640px | Collapsed sidebar, stacked layout |
| `md` | 768px | Sidebar at 56px (icon-only) |
| `lg` | 1024px | Sidebar at 220px (expanded), main content area |
| `xl` | 1280px | Default admin portal target |
| `2xl` | 1536px | Wide dashboard, multi-column panels |

**Target design width:** 1280px (xl). All screen specs below reference this breakpoint.  
**Minimum supported:** 1024px (lg) — sidebar collapses to icon-only.

---

## Part 5 — Screen Inventory

### Screen Index

| ID | Route | Title | Required Roles | Source FRs |
|---|---|---|---|---|
| `AUTH-001` | `/login` | SSO Login | — | FR-018 |
| `SHELL-001` | (global) | App Shell | Any authenticated | FR-018, FR-041 |
| `DASH-001` | `/` | Executive Overview | Any authenticated | FR-044 |
| `CONN-001` | `/connectors` | Connector List | PLATFORM_ENGINEER, ADMIN | FR-006, FR-009, FR-020 |
| `CONN-002` | `/connectors/new`, `/connectors/:id/edit` | Add / Edit Connector | PLATFORM_ENGINEER, ADMIN | FR-006, FR-007, FR-008 |
| `CONN-003` | `/connectors/:id` | Connector Health Detail | PLATFORM_ENGINEER, ADMIN | FR-009, FR-010 |
| `KS-001` | `/knowledge-sources` | Knowledge Sources List | PLATFORM_ENGINEER, ADMIN | FR-011, FR-021 |
| `KS-002` | `/knowledge-sources/new`, `/knowledge-sources/:id/edit` | Add / Edit Knowledge Source | PLATFORM_ENGINEER, ADMIN | FR-011, FR-012, FR-013 |
| `POL-001` | `/policies` | Policy List | SECURITY_OFFICER, ADMIN | FR-033, FR-034 |
| `POL-002` | `/policies/new`, `/policies/:id` | Policy Editor | SECURITY_OFFICER, ADMIN | FR-034, FR-035, FR-042 |
| `POL-003` | `/policies/:id/simulate` | Policy Simulation | SECURITY_OFFICER, ADMIN | FR-035 |
| `REPLAY-001` | `/traces` | Replay Explorer | AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN | FR-019, FR-036 |
| `REPLAY-002` | `/traces/:id` | Trace Timeline | AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN | FR-037, FR-038, FR-043 |
| `AUDIT-001` | `/audit-log` | Audit Log | AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN | FR-045 |
| `AUDIT-002` | `/audit-log/verify` | Chain Integrity Verification | AUDITOR, SECURITY_OFFICER, ADMIN | FR-045, FR-043 |
| `USER-001` | `/users` | User Management | ADMIN | FR-041 |
| `USER-002` | `/users/:id` | User Role Assignment | ADMIN | FR-041, FR-018 |
| `MODEL-001` | `/models` | Model Registry | PLATFORM_ENGINEER, ADMIN | FR-031, FR-058 |
| `MODEL-002` | `/models/add` | Add / Edit Model | PLATFORM_ENGINEER, ADMIN | FR-031, FR-051 |
| `MODEL-003` | `/models/weights` | Routing Weights | PLATFORM_ENGINEER, ADMIN | FR-031, FR-058 |
| `OBS-001` | `/observability` | Observability Dashboard | DEVOPS_SRE, MANAGER, ADMIN | FR-044, FR-047, FR-056 |
| `ERR-001` | `/403` | Access Denied | Any authenticated | — |
| `ERR-002` | `/login` | Unauthenticated Redirect | — | FR-018 |

---

### SHELL-001 — App Shell

**Layout (1280px):**
- **Left sidebar** — fixed, 220px wide; collapses to 56px on `md`
  - Logo + product name (top, 64px height)
  - Primary nav items (icon + label + active indicator)
  - Collapsible section dividers: "Data Sources", "Governance", "Observability", "Platform"
  - User avatar + name + role chip (bottom, 56px height)
- **Top bar** — fixed, 56px height, full width minus sidebar
  - Breadcrumb trail (left-aligned)
  - Search trigger `/` shortcut (center, 320px input, ghost until focused)
  - Notification bell + count badge (right)
  - Dark mode toggle (right)
- **Main content area** — scrollable, padding `space-8` (horizontal) + `space-12` (top)

**Navigation items (ordered):**
1. Dashboard (`/`) — grid icon
2. Connectors (`/connectors`) — plug icon
3. Knowledge Sources (`/knowledge-sources`) — database icon
4. Policies (`/policies`) — shield-check icon
5. Replay Explorer (`/traces`) — play-circle icon
6. Audit Log (`/audit-log`) — list-check icon
7. Users (`/users`) — users icon
8. Models (`/models`) — cpu icon
9. Observability (`/observability`) — chart-bar icon
10. Settings (`/settings`) — cog icon

**Nav item states:**
- `default` — `text-secondary`, no background
- `hover` — `text-primary`, `surface-raised` background, 80ms transition
- `active` — `text-on-accent` or `text-link` with `surface-accent` background, 2px left border `brand-blue-500`
- `focus-visible` — 2px `border-focus` outline, 2px offset

**Sidebar collapse behavior (md breakpoint):**
- Labels hidden; icon centered in 56px column
- Tooltip on hover reveals label (floating elevation, `r-sm`)

**Accessibility:**
- `<nav aria-label="Main navigation">` wrapping sidebar
- Each nav item is `<a>` or `<button>` with `role="link"` implicit
- Active item: `aria-current="page"`
- Skip-to-content link as first focusable element

---

### AUTH-001 — SSO Login Redirect

**Layout:** centered, single card (360px wide), `surface-canvas` background

**States:**
| State | Description |
|---|---|
| `default` | Product logo, product name (`type-h2`), "Sign in with your organization account" (`type-body`), primary CTA "Continue with SSO", divider, "Need help?" link |
| `loading` | CTA replaced by spinner + "Redirecting to Keycloak…" |
| `error` | Inline error below CTA: `text-danger` + danger icon, "Authentication failed. Please try again." |

**Components:** `<Card>`, `<Button variant="primary">`, `<Spinner>`, `<InlineAlert variant="danger">`

**A11y:** `<main>` landmark; form `role="form"` with `aria-label="Sign in"`; error is `role="alert"` `aria-live="assertive"`

---

### DASH-001 — Executive Overview Dashboard

**Source FRs:** FR-044  
**Required roles:** Any authenticated

**Layout:** 3-column grid at 1280px; falls to 2-column at 1024px

**Sections:**

#### Stat Bar (full width, 5 KPI tiles)

| Metric | Format | Icon |
|---|---|---|
| Total Requests (24h) | `type-display`, tabular-nums | activity |
| Active Sessions | `type-display` | users |
| Total AI Cost (24h) | `$X.XX`, `type-display` | dollar-sign |
| Avg Latency | `Xms`, `type-display` | clock |
| Policy Violations (24h) | `type-display`, `text-danger` if > 0 | shield-exclamation |

**States per tile:**
- `loading` — skeleton 48px × full width, opacity pulse
- `error` — `—` text with `text-muted` tooltip on hover
- `value` — label (`type-caption`, `text-secondary`) above value

#### Charts (3-column grid row)

- **Column 1 (2-col span):** Requests over time — line chart, 24h or 7d toggle, `brand-blue-500` line, `surface-canvas` background, gridlines in `border-subtle`
- **Column 2 (1-col span):** Model usage — horizontal bar chart, one bar per model, `text-secondary` labels, tabular numerals for token counts

#### Connector Health Row

Table: Connector Name | Type | Status (badge) | Last Sync | Error Count

Status badge variants:
- `healthy` — `feedback-success` text, `surface-success` background, `r-full`
- `degraded` — `feedback-warning` text, `surface-warning` background
- `unhealthy` — `feedback-danger` text, `surface-danger` background
- `syncing` — `feedback-info` text, `surface-info` background, spinning icon

#### Recent Policy Violations

Table: Timestamp | Policy | User | Action Taken  
Empty state: "No violations in the last 24 hours" — centered, `text-muted`, `type-body`

**A11y:**
- `<main aria-labelledby="page-heading">`
- Charts wrapped in `<figure>` with `<figcaption>` (screen-reader summary of data)
- All stat tiles have `aria-label="Metric name: value"`

---

### CONN-001 — Connector List

**Source FRs:** FR-006, FR-009, FR-020  
**Required roles:** PLATFORM_ENGINEER, ADMIN

**Layout:** Page heading + action bar + filterable table

**Action bar:**
- Left: Page title "Connectors" (`type-h2`)
- Right: `<Button variant="primary">Add Connector</Button>` → navigates to `CONN-002`

**Filter bar (below heading):**
- Type filter: `<Select>` with options All / GitHub / Confluence / Jira / GitLab / Custom
- Status filter: `<Select>` with options All / Healthy / Degraded / Unhealthy / Syncing
- Search: `<TextInput placeholder="Search connectors…" aria-label="Search connectors">` — debounced 300ms

**Table columns:**
| Column | Type | Sortable |
|---|---|---|
| Name | text | ✓ |
| Type | badge | ✓ |
| Auth | chip (OAuth2 / API Key / PAT / JWT) | — |
| Status | status badge | ✓ |
| Last Sync | relative time (tabular-nums) | ✓ |
| Next Sync | relative time | — |
| Actions | icon button group (edit, delete) | — |

**Row states:**
- `default` — `surface-canvas` background
- `hover` — `surface-raised` background, 80ms
- `selected` — `surface-accent` background
- `error-row` — `surface-danger` background, danger left-border 1px

**Table states:**
- `loading` — 5 skeleton rows, each 48px height
- `empty` — centered illustration placeholder, "No connectors configured yet", "Add your first connector" text-link
- `error` — `<InlineAlert variant="danger">` above table

**Row action: Delete**
- Opens `<ConfirmationModal>` with destructive action pattern
- Modal title: "Delete connector?" / Body: "This will remove the connector and stop all synchronization. This action cannot be undone." / Actions: "Cancel" (secondary) + "Delete" (danger)

**A11y:**
- `<table>` with `<caption>` (visually hidden)
- Sort buttons: `aria-sort="ascending"` / `"descending"` / `"none"`
- Delete buttons: `aria-label="Delete connector [name]"`

---

### CONN-002 — Add / Edit Connector

**Source FRs:** FR-006, FR-007, FR-008  
**Required roles:** PLATFORM_ENGINEER, ADMIN

**Layout:** 2-column split — form (left, 600px) + live preview / connectivity test panel (right)

**Form sections:**

1. **Connector Type** — `<RadioGroup>` with icon tiles: GitHub, Confluence, Jira, GitLab, Custom API
2. **Basic Info** — Name (`required`), Description (optional)
3. **Authentication** — conditional based on connector type
   - `OAuth2` — Client ID, Client Secret (password input), Authorization URL, Token URL, Scope
   - `API Key` — API Key (password input with reveal toggle), Header Name
   - `PAT` — Personal Access Token (password input), Base URL
   - `JWT` — JWKS URL, Audience, Issuer
4. **Synchronization** — Schedule interval (`<Select>`: Every 15 min / 30 min / 1 hr / 4 hr / 24 hr / Manual), Indexing Strategy (`<RadioGroup>`: Semantic + Keyword / Keyword only / Semantic only)
5. **Advanced** — Timeout (number, ms), Max retries (number), Custom headers (key-value pair list)

**Right panel:**
- Connectivity test trigger: `<Button variant="secondary">Test Connection</Button>`
- States: idle, testing (spinner), success (check + latency ms), failure (error + diagnostic message)

**Form footer (sticky):**
- Left: "Test Connection" button
- Right: "Cancel" (navigates back) + "Save Connector" (primary)

**Validation:**
- Required fields highlighted on submit if empty
- URL fields validated as valid URL format (inline error below field on blur)
- Secret fields show strength indicator for PAT / API key length

**A11y:**
- `<form aria-label="Connector configuration">`
- Password inputs: `aria-describedby` pointing to reveal-toggle
- Connectivity test result: `role="status"` `aria-live="polite"`

---

### CONN-003 — Connector Health Detail

**Source FRs:** FR-009, FR-010

**Layout:** Page heading + 3-section layout: Status summary | Sync history | Configuration summary

**Status summary card:**
- Large status badge, connector name (`type-h2`)
- Key stats row: Last Sync (timestamp), Next Sync (relative), Documents Indexed (count), Errors (24h)
- Actions: "Trigger Sync Now" (secondary), "Edit Connector" (secondary), "Delete" (danger)

**Sync history table:**
| Column | Type |
|---|---|
| Started | ISO timestamp |
| Duration | mm:ss |
| Documents | count |
| Status | success / partial / failed badge |
| Error | text (expandable on click) |

States: `loading` (skeleton), `empty` ("No sync runs yet"), `error` (inline alert)

**Configuration summary:** read-only key-value list, secrets masked as `••••••••`

---

### KS-001 — Knowledge Sources List

**Source FRs:** FR-011, FR-021  
**Required roles:** PLATFORM_ENGINEER, ADMIN

Identical layout pattern to `CONN-001` with these column differences:

| Column | Notes |
|---|---|
| Source | text + type chip (repo / folder / project / API) |
| Connector | linked to `CONN-003` |
| Priority | badge (High / Medium / Low) in brand-relative colors (not semantic) |
| Index Size | document count, tabular-nums |
| Last Refresh | relative time |

Empty state: "No knowledge sources configured. Add a knowledge source to begin indexing enterprise content."

---

### KS-002 — Add / Edit Knowledge Source

**Source FRs:** FR-011, FR-012, FR-013

**Form sections:**
1. **Connector** — `<Select>` from registered healthy connectors; if none, shows "No connectors available" with link to `CONN-002`
2. **Source Details** — source-type conditional:
   - Repository: owner/repo, branch, include/exclude path patterns
   - Confluence: Space key, include labels
   - Jira: Project key, issue types, status filter
3. **Indexing** — Priority (`<RadioGroup>`: High / Medium / Low), Strategy (`<Select>`: Semantic + Keyword / Keyword / Semantic), Chunk size (tokens), Overlap (tokens)
4. **Schedule** — Refresh interval (`<Select>`)

---

### POL-001 — Policy List

**Source FRs:** FR-033, FR-034  
**Required roles:** SECURITY_OFFICER, ADMIN

**Table columns:**

| Column | Notes |
|---|---|
| Name | text, linked to `POL-002` |
| Version | `type-mono-sm`, tabular-nums |
| Status | badge: Active / Draft / Archived |
| Author | text |
| Last Modified | relative time |
| Actions | Edit / Activate / Archive / View History |

**Status badge variants:**
- `active` — `feedback-success` text, `surface-success` background
- `draft` — `text-secondary`, `surface-raised` background
- `archived` — `text-muted`, `surface-sunken` background, strikethrough optional

**Bulk actions bar** (visible when ≥ 1 row selected):
- Count indicator: "3 policies selected"
- Actions: "Activate selected" (primary) / "Archive selected" (secondary)

---

### POL-002 — Policy Editor

**Source FRs:** FR-034, FR-035, FR-042  
**Required roles:** SECURITY_OFFICER, ADMIN

**Layout:** 3-column split — metadata sidebar (left, 280px) + Rego editor (center, flex) + test output panel (right, 320px, collapsible)

**Metadata sidebar:**
- Policy name (editable inline)
- Version label (`type-mono-sm`, auto-incremented)
- Description (textarea, max 200 chars)
- Status chip (Draft / Active / Archived)
- Author, Created, Modified (read-only)

**Rego editor (center):**
- Monospace editor pane, `type-mono` (`IBM Plex Mono`), `surface-sunken` background
- Line numbers (left gutter, `text-muted`)
- Syntax highlighting: keywords in `brand-blue-600`, strings in `success-600`, comments in `text-muted`
- Error underlines in `danger-600`

**Test output panel (right):**
- "Run Simulation →" trigger (navigates to `POL-003` with current policy content)
- Last simulation result summary:
  - Input summary (`type-small`)
  - Decision: ALLOW (green badge) / DENY (danger badge)
  - Matched rules list

**Bottom action bar (sticky):**
- Left: "Discard changes" (ghost)
- Right: "Save as Draft" (secondary) | "Activate Policy" (primary)

**Activate confirmation modal:**
- Title: "Activate policy v{n}?"
- Body: "This will immediately apply to all AI requests. The previous active version will be archived."
- Actions: "Cancel" + "Activate" (primary)

**A11y:**
- Editor region: `role="region"` `aria-label="Policy editor"`, `aria-live="off"`
- Rego errors: `role="alert"` `aria-live="assertive"` for compile errors

---

### POL-003 — Policy Simulation

**Source FRs:** FR-035  
**Required roles:** SECURITY_OFFICER, ADMIN

**Layout:** 2-column — input panel (left) + decision output (right)

**Input panel:**
- Sample request JSON editor (`<CodeEditor>`, `type-mono`)
- Pre-populated with schema template on load
- "Run Simulation" primary CTA

**Output panel:**
- Decision badge: `ALLOW` (success) / `DENY` (danger), `type-h3`, full width
- Matched rule path: `type-mono-sm`, copyable
- Reason text: human-readable explanation
- Trace tree: collapsible rule evaluation tree (rule → sub-rules → outcome)

**States:**
- `idle` — placeholder "Run a simulation to see the policy decision here"
- `loading` — spinner + "Evaluating…"
- `allow` — success surface, ALLOW badge
- `deny` — danger surface, DENY badge, matched rule highlighted

---

### REPLAY-001 — Replay Explorer

**Source FRs:** FR-019, FR-036  
**Required roles:** AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN

**Layout:** Full-width filter bar + paginated table

**Filter bar:**
- Date range: `<DateRangePicker>` (from / to)
- User ID: text input
- Session ID: text input (`type-mono` in input)
- Intent class: `<Select>` (All / Code Search / Incident Investigation / Architecture Query / …)
- Execution ID: text input (`type-mono`)

**Table columns:**

| Column | Notes |
|---|---|
| Execution ID | `type-mono-sm`, first 8 chars, copyable on click |
| Timestamp | ISO with milliseconds, tabular-nums |
| User | text |
| Intent | chip |
| Model Used | badge |
| Latency | ms, tabular-nums, colored threshold (>2000ms = warning, >5000ms = danger) |
| Tokens | in / out split, tabular-nums |
| Status | Completed / Policy Blocked / Failed badge |

Row click → navigates to `REPLAY-002`

---

### REPLAY-002 — Trace Timeline View

**Source FRs:** FR-037, FR-038, FR-043

**Layout:** Execution header + horizontal timeline + side-by-side detail

**Execution header:**
- Execution ID (`type-mono-sm`), User, Timestamp
- Summary stats: Total latency, Total tokens, Model selected, Policy decision

**Horizontal timeline (Gantt-style):**
Each agent phase is a horizontal bar:
- Intent Detection
- Context Planning
- Retrieval (may be parallel, shown as overlapping bars)
- Knowledge Graph
- Ranking
- Compression
- Governance
- Model Router
- Response Builder

Color:
- Completed phase: `brand-blue-500` fill, duration label in ms
- Governance block (if DENY applied to chunk): `danger-600` fill
- Active/selected phase: `brand-blue-700` fill, 2px outline

Click on phase bar → opens detail panel below

**Detail panel (below timeline):**
- Phase name + duration
- Input: collapsed JSON viewer (`<CodeViewer>`, collapsible sections)
- Output: collapsed JSON viewer
- Governance actions (if applicable): list of redacted fields with reason
- Model routing decision (for Router phase): evaluated models table, winner highlighted

**A11y:**
- Timeline bars: `role="row"` in a `<table>` structure with `caption`
- Each phase bar: `aria-label="[Phase name], [duration]ms, [status]"`, `tabindex="0"`, Enter to expand

---

### REPLAY-003 — Agent Phase Drill-Down *(drawer overlay over REPLAY-002)*

Opens as a `<Drawer>` from the right (360px wide, `floating` elevation) when a timeline phase bar is activated.

**Content:**
- Phase name (`type-h4`)
- Start time / end time / duration
- Agent version (`type-mono-sm`)
- Tabbed content: Input | Output | Decisions | Errors
- Each tab shows a `<CodeViewer>` or structured data table

---

### AUDIT-001 — Audit Log

**Source FRs:** FR-045  
**Required roles:** AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN

**Layout:** Filter bar + table + "Load more" pagination

**Filter bar:**
- User ID: text input
- Action: `<Select>` populated from `AdminActionType` enum values
- Resource Type: text input
- Resource ID: text input
- From date: `<DateTimePicker>`
- To date: `<DateTimePicker>`
- "Apply" (primary) + "Clear" (ghost) buttons

**Table columns:**

| Column | Type | Notes |
|---|---|---|
| Timestamp | ISO datetime | `type-mono-sm`, tabular-nums |
| Action | action chip | color-coded by category (policy.* = info, model.* = brand, connector.* = neutral) |
| Resource Type | text | |
| Resource ID | `type-mono-sm` | truncated to 20 chars, full value in tooltip |
| Actor | text | `type-body` |
| IP Address | `type-mono-sm` | |
| Row Hash | `type-mono-sm` | first 8 chars, full in tooltip |

**Row expansion:**
- Clicking a row expands an inline detail panel (not a drawer, to maintain table context)
- Shows `before_state` and `after_state` as side-by-side JSON diff
- `before_state = null` shows "Created (no prior state)"

**Load more pagination:**
- "Load more" button at table footer, centered
- Shows count: "Showing 50 of ~N entries"
- Disabled when `next_cursor` is `null`

**Chain Integrity action:**
- Header right: "Verify Chain Integrity" button (secondary, shield icon) → navigates to `AUDIT-002`

**States:**
- `loading` — 10 skeleton rows
- `empty` — "No audit log entries match your filters" with clear-filters link
- `error` — `<InlineAlert variant="danger">`

**A11y:**
- `<table aria-label="Audit log entries">`
- Filter form: `<form role="search" aria-label="Audit log filters">`
- All inputs: `aria-label` on each field
- "Load more": `aria-label="Load next page of audit log entries"`

---

### AUDIT-002 — Chain Integrity Verification

**Source FRs:** FR-045, FR-043  
**Required roles:** AUDITOR, SECURITY_OFFICER, ADMIN

**Layout:** Centered content, 720px max-width

**Initial state (idle):**
- Page heading "Audit Log Integrity" (`type-h2`)
- Description: "Re-computes the SHA-256 chain hash over every row and reports the first mismatch. For large audit logs this may take several seconds." (`type-body`, `text-secondary`)
- "Start Verification" primary button

**Verification states:**

| State | Visual |
|---|---|
| `idle` | Button + description |
| `loading` | Progress indicator: spinning icon + "Scanning N rows…" updating via polling |
| `intact` | Full-width `<Alert variant="success">` — "Chain Intact — N rows verified, no tampering detected." Hash of last row shown in `type-mono-sm` |
| `tampered` | Full-width `<Alert variant="danger">` — "Integrity Failure — First mismatch at row N. The chain has been tampered or corrupted." Row index + row ID shown. |

**Tampered detail card (shown when `first_mismatch` is not null):**
- Row index (1-based): `type-h4`
- Row ID: `type-mono-sm`, copyable
- "Download Incident Report" button (secondary) — exports JSON report

**A11y:**
- Result alerts: `role="alert"` `aria-live="assertive"`
- Loading status: `role="status"` `aria-live="polite"`

---

### USER-001 — User Management

**Source FRs:** FR-041  
**Required roles:** ADMIN

**Table columns:**

| Column | Notes |
|---|---|
| User | Avatar (initials) + Name + Email |
| Role | role chip |
| Team / Dept | text, optional |
| Last Active | relative time |
| Actions | Edit role / Deactivate |

Role chip color map:

| Role | Token |
|---|---|
| `admin` | `brand-blue-600` fill, `text-on-accent` |
| `security_officer` | `danger-600` fill, `text-on-accent` |
| `auditor` | `warning-600` fill, `text-on-accent` |
| `platform_engineer` | `success-600` fill, `text-on-accent` |
| `devops_sre` | `info-600` fill, `text-on-accent` |
| `developer` | `neutral-400` fill, `text-on-accent` |
| `manager` | `neutral-700` fill, `text-on-accent` |

---

### USER-002 — User Role Assignment

**Layout:** Role assignment form within a `<Drawer>` (400px) or full page

**Form:**
- User summary card (avatar, name, email — read-only)
- `<RadioGroup>` for role selection (one role per user), each option shows role name + permission list bullets
- Team (text input, optional)
- Department (text input, optional)

**Footer:** "Cancel" + "Save Changes" (primary)

**Confirmation:** Changing a role shows an inline warning: "This will immediately change the user's access permissions."

---

### MODEL-001 — Model Registry

**Source FRs:** FR-031, FR-058  
**Required roles:** PLATFORM_ENGINEER, ADMIN

**Table columns:**

| Column | Notes |
|---|---|
| Model ID | `type-mono-sm` |
| Provider | chip (OpenAI / Anthropic / Google / Ollama / vLLM / LM Studio) |
| Display Name | text |
| Coding Score | progress bar (0–100), tabular-nums |
| Reasoning Score | progress bar |
| Context Window | K tokens, tabular-nums |
| Cost / 1K | `$X.XXXX`, tabular-nums |
| Avg Latency | ms, tabular-nums |
| Status | Healthy / Degraded / Unavailable badge |
| Active | toggle switch |

---

### MODEL-002 — Add / Edit Model

**Form sections:**
1. Provider + Model ID (from provider's model list)
2. Display name, Description
3. Capability scores — Coding (0–100, slider), Reasoning (0–100, slider)
4. Cost configuration — Cost per 1K input tokens, Cost per 1K output tokens
5. Health check — Endpoint URL, health check interval

---

### MODEL-003 — Routing Weights

**Source FRs:** FR-031, FR-058

**Layout:** Drag-reorderable list of models with weight sliders

**Per-model row:**
- Model name + provider badge
- Weight slider (0–100), numeric input (tabular-nums) synced with slider
- Priority rank (auto-calculated from relative weights)

**Constraint:** Weights are relative (not required to sum to 100 — displayed as normalized percentages)

**Footer:** "Reset to defaults" (ghost) + "Save Weights" (primary)

---

### OBS-001 — Observability Dashboard

**Source FRs:** FR-044, FR-047, FR-056  
**Required roles:** DEVOPS_SRE, MANAGER, ADMIN

**Layout:** Tab navigation: Overview | AI Operations | Connectors | Governance | Alerts

#### Overview tab:
- KPI bar: Requests (24h) / Active Sessions / Total Cost (24h) / Avg Latency / Uptime %
- Requests over time (line chart, 1hr/6hr/24hr/7d toggle)
- Top 5 models by usage (horizontal bar chart)
- Recent alerts table (last 10)

#### AI Operations tab:
- Agent execution time breakdown (stacked bar per agent phase)
- Intent distribution (horizontal bar chart by intent class)
- Token budget utilization: avg compression ratio, target vs actual
- P50 / P95 / P99 latency stats (tabular-nums)

#### Connectors tab:
- Per-connector health timeline (sparklines, 24h)
- Sync error rate table (connector / error count / last error / status)

#### Governance tab:
- Policy evaluations: Allow vs Deny ratio (donut chart)
- Blocked requests count by policy name (horizontal bar)
- Secrets masked count, PII detections count (KPI tiles)

#### Alerts tab:
- Active alerts table: Severity | Alert Name | Triggered At | Affected Component | Status
- Severity color: Critical = `danger-600`, Warning = `warning-600`, Info = `info-600`
- "Acknowledge" action per alert row

---

### ERR-001 — Access Denied (403)

**Layout:** Centered, 480px max-width, vertically centered in viewport

**Content:**
- "403" in `type-display`, `text-muted`
- "Access Denied" in `type-h2`, `text-primary`
- "You don't have permission to view this page. Contact your administrator to request access." in `type-body`, `text-secondary`
- "Return to Dashboard" (primary) + "Contact Support" (secondary, link)

---

## Part 6 — Component Inventory

### Core Interactive Components

| Component | Variants | Key States |
|---|---|---|
| `<Button>` | primary / secondary / ghost / danger / link | default, hover, active, focus, disabled, loading |
| `<TextInput>` | default / search / password | default, focus, filled, error, disabled |
| `<Select>` | single / multi | default, open, selected, error, disabled |
| `<RadioGroup>` | default / tile | default, selected, disabled |
| `<Checkbox>` | default / indeterminate | unchecked, checked, indeterminate, disabled |
| `<Toggle>` | sm / md | off, on, disabled |
| `<DatePicker>` | date / datetime / range | default, open, selected, error |
| `<Textarea>` | default | default, focus, filled, error |
| `<Slider>` | single / range | default, active, disabled |

### Layout Components

| Component | Notes |
|---|---|
| `<Card>` | `r-lg`, `border-subtle` + `resting` elevation; variants: default / raised / sunken |
| `<Modal>` | `floating` elevation, `r-lg`, `r-full` close button; sizes: sm (360px) / md (520px) / lg (720px) |
| `<Drawer>` | right-side overlay, widths: 360px / 400px / 520px, `floating` elevation |
| `<Table>` | `r-none` cells, `border-strong` row separators, sortable headers, sticky header option |
| `<DataGrid>` | high-density table, 36px row height, virtual scroll for >200 rows |
| `<Tabs>` | underline variant for page-level; filled pill variant for panels |
| `<Accordion>` | flush border, `border-subtle` dividers |

### Feedback Components

| Component | Variants | Notes |
|---|---|---|
| `<Alert>` | success / warning / danger / info | inline + icon, full-width option |
| `<Toast>` | success / warning / danger / info | top-right, auto-dismiss 4s, max 3 stacked |
| `<Badge>` | solid / subtle / outline | `r-full`, `type-caption` |
| `<Skeleton>` | text / block / avatar | opacity pulse, 1200ms, ease-in-out |
| `<Spinner>` | sm (16px) / md (24px) / lg (40px) | brand-blue-500, no label needed at sm |
| `<StatusPip>` | healthy / degraded / unhealthy / syncing | 8px circle, `r-full` |
| `<ProgressBar>` | default / thin | `brand-blue-500` fill, `neutral-200` track |
| `<Tooltip>` | default | `floating` elevation, `r-xs`, max-width 240px, delayed 300ms |
| `<ConfirmationModal>` | standard / destructive | wraps `<Modal md>`, two-action footer |

### Data Display Components

| Component | Notes |
|---|---|
| `<CodeViewer>` | read-only, `IBM Plex Mono`, line numbers, copy button, collapsible |
| `<CodeEditor>` | writable, `IBM Plex Mono`, line numbers, syntax highlight (Rego / JSON) |
| `<JSONDiff>` | before / after side-by-side, added lines in `surface-success`, removed in `surface-danger` |
| `<StatTile>` | KPI tile: label + value + trend arrow |
| `<LineChart>` | simple line chart, `brand-blue-500` line, `border-subtle` gridlines |
| `<BarChart>` | horizontal bar chart, single-hue, tabular-nums labels |
| `<DonutChart>` | 2-3 segment max, center stat, `type-h4` |
| `<Sparkline>` | inline trend, 60px × 24px, no axes |
| `<GanttTimeline>` | horizontal phase bars (Replay timeline component) |
| `<KeyValueList>` | label-value pairs, `text-secondary` label, `text-primary` value |

### Navigation Components

| Component | Notes |
|---|---|
| `<Sidebar>` | collapsible, 220px / 56px, auto-collapse at md breakpoint |
| `<TopBar>` | fixed, 56px, breadcrumb + search + actions |
| `<Breadcrumb>` | text links with `›` separator, current page is non-link |
| `<PageHeader>` | heading + description + action slot |
| `<FilterBar>` | horizontal filter row with label, inputs, apply/clear |
| `<Pagination>` | "Load more" variant for cursor-based APIs; numbered variant for offset APIs |
| `<CommandPalette>` | `⌘K` trigger, floating, `r-lg`, fuzzy search all nav items + recent |

---

## Part 7 — Interaction Flows

### Flow 1 — Add Connector (UC-003)

```
CONN-001 ["Add Connector"]
  → CONN-002 [form: select type → fill auth → configure sync]
    → [Test Connection] success?
      ├── yes → sticky footer "Save Connector" enabled
      └── no  → inline error in right panel, form remains open
  → [Save Connector]
    → success: Toast "Connector saved" (success) + redirect CONN-001
    → error:   InlineAlert (danger) above form footer
```

### Flow 2 — Policy Lifecycle (UC-007)

```
POL-001 ["Create New Policy"]
  → POL-002 [editor: name + rego content]
    → [Save as Draft]
      → success: version incremented, status = Draft
    → [Run Simulation]
      → POL-003 [input sample → run → ALLOW/DENY result]
        → [Back to Editor]
    → [Activate Policy]
      → ConfirmationModal
        ├── [Cancel] → modal closes
        └── [Activate] → API call
          → success: status = Active, previous version archived, Toast
          → error:   ConfirmationModal shows inline error
```

### Flow 3 — Replay Drill-Down (UC-008)

```
REPLAY-001 [filter → find trace row]
  → REPLAY-002 [timeline renders all agent phases]
    → [click phase bar] → REPLAY-003 Drawer opens
      → [Tab: Input] → JSON viewer
      → [Tab: Output] → JSON viewer
      → [Tab: Decisions] → structured list
      → [Drawer close] → REPLAY-002 restored
```

### Flow 4 — Audit Log Review + Integrity Check

```
AUDIT-001 [set filters → Apply]
  → table loads with cursor pagination
  → [click row] → inline expansion: JSONDiff of before/after state
  → [Verify Chain Integrity]
    → AUDIT-002 [Start Verification]
      → loading: polling progress
      → intact: success alert + row count
      → tampered: danger alert + first mismatch row index
```

### Flow 5 — Connector Status Flow (ongoing)

```
StatusPip + status badge update via WebSocket or 30s polling:
  healthy   → degraded : warning toast "Connector [name] is experiencing issues"
  degraded  → unhealthy: danger toast + alert persists in header notification bell
  * → healthy          : info toast "Connector [name] restored"
```

---

## Part 8 — Accessibility Checklist

All screens must satisfy the following before handoff:

| Category | Requirement |
|---|---|
| Contrast | Body text ≥ 4.5:1 against background (WCAG AA). Large text ≥ 3:1. |
| Focus | Every interactive element has a visible focus ring (2px `border-focus`, 2px offset). |
| Keyboard | Full keyboard navigation. No mouse-only interactions. |
| Screen reader | All icons have `aria-label` or `aria-hidden="true"`. |
| Forms | Every input has an associated `<label>`. Errors are linked via `aria-describedby`. |
| Live regions | Dynamic content (toast, status, polling results) uses `aria-live`. |
| Tables | `<table>` elements have `<caption>` and `<th scope="col/row">`. |
| Images | No decorative SVG without `aria-hidden="true"`. |
| Motion | `prefers-reduced-motion` fallback applied globally. |
| Color alone | Status is never communicated by color alone (always icon + text accompanies). |
| Skip link | "Skip to main content" is the first focusable element on every page. |

---

## Part 9 — Anti-Pattern Audit (Pre-Handoff Gate)

Before any design file is shipped, verify zero occurrences of:

| # | Anti-pattern | Detection |
|---|---|---|
| 1 | Gradient text on headings or CTAs | `background-clip: text` or `-webkit-background-clip: text` |
| 2 | Glassmorphism as surface decoration | `backdrop-filter: blur(...)` without real content behind |
| 3 | Colored left/right border > 1px on cards or alerts | `border-left: [2-9]+px` solid color |
| 4 | Single font family for both display and body | Only Inter / DM Sans / Roboto / Poppins used |
| 5 | Purple-to-blue hero gradient | `linear-gradient(135deg, #6366F1, #3B82F6)` or equivalent |
| 6 | Hex literals in semantic token layer | `#[0-9a-fA-F]{6}` outside primitive table |
| 7 | Lorem ipsum placeholder in hi-fi screens | `lorem ipsum` (case-insensitive) |
| 8 | Thick color border on alert strip | `border-(left\|right): [3-9]+px` |
| 9 | Tabular numerals missing on numeric columns | Numeric column without `font-variant-numeric: tabular-nums` |
| 10 | Motion exceeding 400ms on any non-orchestrated element | `transition-duration: [4-9]\d\d\d?ms` |

---

*End of ContextIQ Figma Specification v1.0*
