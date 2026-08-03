# ContextIQ — Component Inventory

## Metadata

| Field | Value |
|---|---|
| Artifact | `wireframe / component_inventory` |
| Source | `figma_spec_contextiq.md` Part 6 |
| Output path | `.propel/context/wireframes/component-inventory.md` |

---

## 1. Core Interactive Components

| Component | File path (anticipated) | Variants | States | Used in screens |
|---|---|---|---|---|
| `<Button>` | `src/components/ui/Button.tsx` | `primary` · `secondary` · `ghost` · `danger` · `link` | default, hover, active, focus, disabled, loading | all |
| `<TextInput>` | `src/components/ui/TextInput.tsx` | `default` · `search` · `password` | default, focus, filled, error, disabled | CONN-002, KS-002, POL-002, MODEL-002, USER-002, AUDIT-001 |
| `<Select>` | `src/components/ui/Select.tsx` | `single` · `multi` | default, open, selected, error, disabled | CONN-001, CONN-002, KS-001, KS-002, POL-001, REPLAY-001, USER-001, MODEL-001 |
| `<RadioGroup>` | `src/components/ui/RadioGroup.tsx` | `default` · `tile` | default, selected, disabled | CONN-002, USER-002 |
| `<Checkbox>` | `src/components/ui/Checkbox.tsx` | `default` · `indeterminate` | unchecked, checked, indeterminate, disabled | POL-001 |
| `<Toggle>` | `src/components/ui/Toggle.tsx` | `sm` · `md` | off, on, disabled | MODEL-001 |
| `<DatePicker>` | `src/components/ui/DatePicker.tsx` | `date` · `datetime` · `range` | default, open, selected, error | REPLAY-001, AUDIT-001 |
| `<Textarea>` | `src/components/ui/Textarea.tsx` | `default` | default, focus, filled, error | POL-002 (description) |
| `<Slider>` | `src/components/ui/Slider.tsx` | `single` · `range` | default, active, disabled | MODEL-003, MODEL-002 |
| `<PasswordInput>` | `src/components/ui/PasswordInput.tsx` | `default` | default, filled, revealed, error | CONN-002 (auth secrets), MODEL-002 (API key) |

---

## 2. Layout Components

| Component | File path | Props / notes | Used in |
|---|---|---|---|
| `<Card>` | `src/components/ui/Card.tsx` | `variant: default\|raised\|sunken` · `padding: sm\|md\|lg` | DASH-001, CONN-003 |
| `<Modal>` | `src/components/ui/Modal.tsx` | `size: sm(360)\|md(520)\|lg(720)` · `title` · `onClose` | CONN-001 (delete confirm), POL-002 (activate confirm) |
| `<Drawer>` | `src/components/ui/Drawer.tsx` | `width: 360\|400\|480\|520` · `side: right` | CONN-002, KS-002, USER-002, MODEL-002, REPLAY-003 |
| `<SlideOverDrawer>` | alias of `<Drawer width={480}>` | focus trap, Escape to close | CONN-002 |
| `<Table>` | `src/components/ui/Table.tsx` | sortable headers, sticky header opt | CONN-001, KS-001, POL-001, REPLAY-001, AUDIT-001, USER-001, MODEL-001 |
| `<DataGrid>` | `src/components/ui/DataGrid.tsx` | 36px rows, virtual scroll >200 rows | AUDIT-001 (large datasets) |
| `<Tabs>` | `src/components/ui/Tabs.tsx` | `variant: underline\|pill` | OBS-001 (page-level), REPLAY-002 (panel) |
| `<Accordion>` | `src/components/ui/Accordion.tsx` | flush border, `border-subtle` dividers | CONN-002 (Advanced section) |
| `<ConfirmationModal>` | `src/components/ui/ConfirmationModal.tsx` | wraps `<Modal md>`, `variant: standard\|destructive` | CONN-001, POL-002 |
| `<PageHeader>` | `src/components/layout/PageHeader.tsx` | `title`, `description`, `action` slot | all list screens |
| `<FilterBar>` | `src/components/layout/FilterBar.tsx` | horizontal filter row | CONN-001, KS-001, POL-001, REPLAY-001, AUDIT-001, USER-001 |

---

## 3. Feedback Components

| Component | File path | Variants | Notes |
|---|---|---|---|
| `<Alert>` | `src/components/ui/Alert.tsx` | `success` · `warning` · `danger` · `info` | inline + icon; full-width option |
| `<Toast>` | `src/components/ui/Toast.tsx` | `success` · `warning` · `danger` · `info` | top-right, auto-dismiss 4s, max 3 stacked |
| `<Badge>` | `src/components/ui/Badge.tsx` | `solid` · `subtle` · `outline` | `r-full`, `type-caption` |
| `<StatusBadge>` | `src/components/domain/StatusBadge.tsx` | `healthy` · `degraded` · `offline` · `syncing` · `active` · `draft` | semantic bg + text + icon |
| `<Skeleton>` | `src/components/ui/Skeleton.tsx` | `text` · `block` · `avatar` | opacity pulse, 1200ms |
| `<Spinner>` | `src/components/ui/Spinner.tsx` | `sm(16)` · `md(24)` · `lg(40)` | `brand-blue-500` |
| `<StatusPip>` | `src/components/ui/StatusPip.tsx` | `healthy` · `degraded` · `unhealthy` · `syncing` | 8px circle |
| `<ProgressBar>` | `src/components/ui/ProgressBar.tsx` | `default` · `thin` | `brand-blue-500` fill |
| `<Tooltip>` | `src/components/ui/Tooltip.tsx` | `default` | floating elevation, 300ms delay |
| `<InlineAlert>` | `src/components/ui/InlineAlert.tsx` | `danger` · `warning` · `info` | above-form placement |

---

## 4. Data Display Components

| Component | File path | Notes |
|---|---|---|
| `<CodeViewer>` | `src/components/ui/CodeViewer.tsx` | read-only, IBM Plex Mono, line numbers, copy button, collapsible |
| `<CodeEditor>` | `src/components/ui/CodeEditor.tsx` | writable, syntax highlight (Rego / JSON), gutter markers |
| `<MonacoEditor>` | `src/components/editors/MonacoEditor.tsx` | wraps Monaco Editor; `language` prop: `rego`\|`json`\|`typescript` |
| `<JSONDiff>` | `src/components/ui/JSONDiff.tsx` | before/after side-by-side, `surface-success`/`surface-danger` line coloring |
| `<StatTile>` | `src/components/ui/StatTile.tsx` | KPI tile: label + value (`type-display`) + trend arrow |
| `<LineChart>` | `src/components/charts/LineChart.tsx` | Recharts wrapper, `brand-blue-500` line, `border-subtle` gridlines |
| `<BarChart>` | `src/components/charts/BarChart.tsx` | horizontal bar, single-hue, tabular-nums labels |
| `<DonutChart>` | `src/components/charts/DonutChart.tsx` | 2–3 segments max, center stat |
| `<Sparkline>` | `src/components/charts/Sparkline.tsx` | 60×24px inline trend, no axes |
| `<GanttTimeline>` | `src/components/domain/GanttTimeline.tsx` | horizontal phase bars for REPLAY-002, click-to-drill |
| `<KeyValueList>` | `src/components/ui/KeyValueList.tsx` | label-value pairs, `text-secondary` label |
| `<JsonDiffViewer>` | `src/components/domain/JsonDiffViewer.tsx` | AUDIT-001 row expansion |

---

## 5. Domain-Specific Components

| Component | File path | Screen(s) |
|---|---|---|
| `<ConnectorStatusHero>` | `src/components/domain/ConnectorStatusHero.tsx` | CONN-003 |
| `<HealthSparkline>` | `src/components/domain/HealthSparkline.tsx` | CONN-003, CONN-001 |
| `<ProbeLogTable>` | `src/components/domain/ProbeLogTable.tsx` | CONN-003 |
| `<AuditLogTable>` | `src/components/domain/AuditLogTable.tsx` | AUDIT-001 |
| `<AuditLogFilterBar>` | `src/components/domain/AuditLogFilterBar.tsx` | AUDIT-001 |
| `<IntegrityResultCard>` | `src/components/domain/IntegrityResultCard.tsx` | AUDIT-002 |
| `<PhaseTimeline>` | `src/components/domain/PhaseTimeline.tsx` | REPLAY-002 |
| `<PhaseTable>` | `src/components/domain/PhaseTable.tsx` | REPLAY-002 |
| `<TraceStatusHero>` | `src/components/domain/TraceStatusHero.tsx` | REPLAY-002 |
| `<PolicyTrendChart>` | `src/components/domain/PolicyTrendChart.tsx` | DASH-001 |
| `<ConnectorHealthList>` | `src/components/domain/ConnectorHealthList.tsx` | DASH-001 |
| `<RecentAuditFeed>` | `src/components/domain/RecentAuditFeed.tsx` | DASH-001 |
| `<WeightSlider>` | `src/components/domain/WeightSlider.tsx` | MODEL-003 |
| `<WeightTotal>` | `src/components/domain/WeightTotal.tsx` | MODEL-003 |
| `<DecisionBadge>` | `src/components/domain/DecisionBadge.tsx` | POL-003, REPLAY-002 |
| `<LintPanel>` | `src/components/domain/LintPanel.tsx` | POL-002 |

---

## 6. Navigation Components

| Component | File path | Notes |
|---|---|---|
| `<SideNav>` | `src/components/layout/SideNav.tsx` | collapsible, 220→56px at md |
| `<TopBar>` | `src/components/layout/TopBar.tsx` | fixed 56px, breadcrumb + search + actions |
| `<Breadcrumb>` | `src/components/ui/Breadcrumb.tsx` | `›` separator, current page non-link |
| `<NavItem>` | `src/components/layout/NavItem.tsx` | icon + label + `aria-current="page"` |
| `<NavSectionLabel>` | `src/components/layout/NavSectionLabel.tsx` | all-caps group header |
| `<UserChip>` | `src/components/layout/UserChip.tsx` | avatar + name + role badge, profile menu trigger |
| `<GlobalSearch>` | `src/components/layout/GlobalSearch.tsx` | `⌘K` / `/` shortcut, CommandPalette trigger |
| `<CommandPalette>` | `src/components/layout/CommandPalette.tsx` | fuzzy search nav + recents |
| `<Pagination>` | `src/components/ui/Pagination.tsx` | "Load more" (cursor) + numbered (offset) variants |
| `<BulkActionBar>` | `src/components/ui/BulkActionBar.tsx` | sticky bottom, count + actions, POL-001 |

---

## 7. Guard / Auth Components

| Component | File path | Notes |
|---|---|---|
| `<RequireAuth>` | `src/auth/RequireAuth.tsx` | Redirects to ERR-002 → `/login` if no session |
| `<RequireRole>` | `src/auth/RequireRole.tsx` | Redirects to ERR-001 → `/403` if role insufficient |
| `<RequireAuditor>` | `src/auth/RequireAuditor.tsx` | Alias: allows AUDITOR, DEVOPS_SRE, SEC_OFFICER, ADMIN |

---

## 8. Screen → Primary Components Cross-Reference

| Screen | Components required (first-order) |
|---|---|
| AUTH-001 | `<Card>`, `<Button>`, `<TextInput>`, `<InlineAlert>` |
| SHELL-001 | `<SideNav>`, `<TopBar>`, `<NavItem>`, `<UserChip>`, `<GlobalSearch>` |
| DASH-001 | `<StatTile>` ×5, `<LineChart>`, `<BarChart>`, `<ConnectorHealthList>`, `<RecentAuditFeed>` |
| CONN-001 | `<PageHeader>`, `<FilterBar>`, `<Table>`, `<StatusBadge>`, `<DropdownMenu>`, `<Pagination>` |
| CONN-002 | `<SlideOverDrawer>`, `<RadioGroup>`, `<TextInput>`, `<Select>`, `<PasswordInput>`, `<Accordion>`, `<Button>`, `<Alert>` |
| CONN-003 | `<ConnectorStatusHero>`, `<KeyValueList>`, `<HealthSparkline>`, `<ProbeLogTable>` |
| KS-001 | `<PageHeader>`, `<FilterBar>`, `<Table>`, `<StatusBadge>`, `<Pagination>` |
| KS-002 | `<Drawer>`, `<Select>`, `<TextInput>`, `<RadioGroup>`, `<Button>` |
| POL-001 | `<PageHeader>`, `<FilterBar>`, `<Table>`, `<Checkbox>`, `<StatusBadge>`, `<BulkActionBar>` |
| POL-002 | `<MonacoEditor>`, `<LintPanel>`, `<TextInput>`, `<Select>`, `<Badge>`, `<Button>`, `<ConfirmationModal>` |
| POL-003 | `<CodeEditor>`, `<Button>`, `<DecisionBadge>`, `<CodeViewer>` |
| REPLAY-001 | `<FilterBar>`, `<Table>`, `<StatusBadge>`, `<Pagination>`, `<DatePicker>` |
| REPLAY-002 | `<TraceStatusHero>`, `<GanttTimeline>`, `<PhaseTable>`, `<Tabs>` |
| REPLAY-003 | `<Drawer>`, `<Tabs>`, `<CodeViewer>`, `<Badge>` |
| AUDIT-001 | `<AuditLogFilterBar>`, `<AuditLogTable>`, `<JsonDiffViewer>`, `<Button>`, `<Pagination>` |
| AUDIT-002 | `<Button>`, `<Alert>`, `<IntegrityResultCard>`, `<Spinner>` |
| USER-001 | `<PageHeader>`, `<FilterBar>`, `<Table>`, `<Badge>` |
| USER-002 | `<Drawer>`, `<RadioGroup>`, `<TextInput>`, `<Badge>`, `<Alert>` |
| MODEL-001 | `<PageHeader>`, `<FilterBar>`, `<Table>`, `<ProgressBar>`, `<Toggle>`, `<StatusBadge>` |
| MODEL-002 | `<Drawer>`, `<Select>`, `<TextInput>`, `<PasswordInput>`, `<Slider>`, `<Button>` |
| MODEL-003 | `<WeightSlider>` ×N, `<WeightTotal>`, `<Button>` |
| OBS-001 | `<Tabs>`, `<StatTile>` ×5, `<LineChart>`, `<BarChart>`, `<DonutChart>`, `<Sparkline>`, `<Table>` |
| ERR-001 | `<Button>` ×2 |
