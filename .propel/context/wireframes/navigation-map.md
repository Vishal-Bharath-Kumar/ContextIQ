# ContextIQ — Navigation Map

## Metadata

| Field | Value |
|---|---|
| Artifact | `wireframe / navigation_map` |
| Source | `figma_spec_contextiq.md` Part 5 SHELL-001 |
| Output path | `.propel/context/wireframes/navigation-map.md` |

---

## 1. Sidebar Navigation — Item Specification

Ordered list of all sidebar items as rendered in SHELL-001. Each item specifies its icon, label, route, required role guard, and active indicator behaviour.

| # | Icon | Label | Route | Minimum Role | Active Border |
|---|---|---|---|---|---|
| — | Logo | ContextIQ | — | — | — |
| 1 | grid-2×2 | Dashboard | `/` | any | `brand-blue-500` left 2px |
| — | — | DATA SOURCES (section) | — | — | — |
| 2 | plug | Connectors | `/connectors` | PLATFORM_ENGINEER, ADMIN | `brand-blue-500` left 2px |
| 3 | database | Knowledge Sources | `/knowledge-sources` | PLATFORM_ENGINEER, ADMIN | `brand-blue-500` left 2px |
| — | — | GOVERNANCE (section) | — | — | — |
| 4 | shield-check | Policies | `/policies` | SECURITY_OFFICER, ADMIN | `brand-blue-500` left 2px |
| — | — | OBSERVABILITY (section) | — | — | — |
| 5 | play-circle | Replay Explorer | `/traces` | AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN | `brand-blue-500` left 2px |
| 6 | list-check | Audit Log | `/audit-log` | AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, ADMIN | `brand-blue-500` left 2px |
| 7 | chart-bar | Observability | `/observability` | DEVOPS_SRE, MANAGER, ADMIN | `brand-blue-500` left 2px |
| — | — | PLATFORM (section) | — | — | — |
| 8 | users | Users | `/users` | ADMIN | `brand-blue-500` left 2px |
| 9 | cpu | Models | `/models` | PLATFORM_ENGINEER, ADMIN | `brand-blue-500` left 2px |
| 10 | cog | Settings | `/settings` | ADMIN | `brand-blue-500` left 2px |
| — | avatar | {name} · {role} | profile menu | — | — |

**Role-visibility rule:** Nav items the user's role cannot access are hidden (not rendered as disabled). This prevents disclosure of feature existence.

---

## 2. Breadcrumb Patterns

Breadcrumb rendered in the TopBar for each screen.

| Screen | Breadcrumb trail |
|---|---|
| DASH-001 | Dashboard |
| CONN-001 | Connectors |
| CONN-002 (create) | Connectors › Add Connector |
| CONN-002 (edit) | Connectors › {name} › Edit |
| CONN-003 | Connectors › {name} |
| KS-001 | Knowledge Sources |
| KS-002 (create) | Knowledge Sources › Add Source |
| KS-002 (edit) | Knowledge Sources › {name} › Edit |
| POL-001 | Policies |
| POL-002 (create) | Policies › New Policy |
| POL-002 (edit) | Policies › {name} |
| POL-003 | Policies › {name} › Simulate |
| REPLAY-001 | Replay Explorer |
| REPLAY-002 | Replay Explorer › {trace-id (first 8 chars)} |
| AUDIT-001 | Audit Log |
| AUDIT-002 | Audit Log › Chain Integrity |
| USER-001 | Users |
| USER-002 | Users › {name} |
| MODEL-001 | Models |
| MODEL-002 | Models › Add Model |
| MODEL-003 | Models › Routing Weights |
| OBS-001 | Observability |
| ERR-001 | (hidden) |

---

## 3. Navigation State Machine

States for each sidebar nav item.

```mermaid
stateDiagram-v2
    [*] --> default
    default --> hover : mouseenter
    hover --> default : mouseleave
    hover --> active : click (route match)
    default --> active : route match on load
    active --> default : route change (no match)
    default --> focused : Tab key
    focused --> active : Enter / Space
    focused --> default : Escape / Tab away
```

**Active detection rule:** An item is `active` when `window.location.pathname` starts with the item's route (prefix match), except Dashboard which uses exact match `/`.

---

## 4. TopBar Actions

| Action | Trigger | Keyboard shortcut | Behaviour |
|---|---|---|---|
| Global Search | Click input or icon | `/` (when not in input focus) | Opens `<CommandPalette>` overlay |
| Notifications | Click bell icon | — | Opens notification popover (right-anchored) |
| Dark Mode Toggle | Click sun/moon icon | — | Toggles `data-theme` on `<html>` |
| Sidebar Collapse | Click `≡` icon | — | Toggles sidebar between 220px and 56px (icon-only) |
| User Menu | Click user chip (bottom of sidebar) | — | Opens profile menu: Profile · Settings · Sign Out |

---

## 5. Keyboard Navigation Contract

| Key | Context | Action |
|---|---|---|
| `Tab` | Anywhere | Next focusable element |
| `Shift+Tab` | Anywhere | Previous focusable element |
| `/` | Non-input focus | Open global search |
| `Escape` | Any overlay (modal, drawer, palette) | Close overlay, return focus to trigger |
| `Enter` or `Space` | Nav item focus | Navigate to route |
| `Arrow Up/Down` | Command palette list | Move selection |
| `Enter` | Command palette item | Activate selection |
| `J` / `K` | Table focus | Move row selection down/up |
