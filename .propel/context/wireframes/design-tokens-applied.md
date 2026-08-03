# ContextIQ — Design Tokens Applied

## Metadata

| Field | Value |
|---|---|
| Artifact | `wireframe / design_tokens_applied` |
| Source | `figma_spec_contextiq.md` Part 2 |
| Fidelity gate | High — included with HTML wireframes |
| Output path | `.propel/context/wireframes/design-tokens-applied.md` |

---

## 1. CSS Custom Property Definitions

All tokens as CSS custom properties. Paste this block into `src/styles/tokens.css` (or equivalent).

```css
/* ────────────────────────────────────────────────
   ContextIQ Design Tokens v1.0
   Source: figma_spec_contextiq.md Part 2
   Color space: OKLCH — perceptually uniform hue
   ──────────────────────────────────────────────── */

:root {
  /* ═══ BRAND BLUE (H = 260) ═══ */
  --brand-blue-50:  oklch(0.98 0.008 260);
  --brand-blue-100: oklch(0.95 0.018 260);
  --brand-blue-200: oklch(0.90 0.035 260);
  --brand-blue-300: oklch(0.82 0.070 260);
  --brand-blue-400: oklch(0.65 0.130 260);
  --brand-blue-500: oklch(0.50 0.185 260);
  --brand-blue-600: oklch(0.43 0.175 260);
  --brand-blue-700: oklch(0.36 0.155 260);
  --brand-blue-800: oklch(0.28 0.120 260);
  --brand-blue-900: oklch(0.20 0.085 260);
  --brand-blue-950: oklch(0.14 0.055 260);

  /* ═══ NEUTRAL (brand-tinted, C = 0.012–0.015, H = 260) ═══ */
  --neutral-0:   oklch(0.99 0.005 260);
  --neutral-50:  oklch(0.97 0.010 260);
  --neutral-100: oklch(0.94 0.015 260);
  --neutral-200: oklch(0.89 0.015 260);
  --neutral-300: oklch(0.78 0.015 260);
  --neutral-400: oklch(0.64 0.015 260);
  --neutral-500: oklch(0.50 0.015 260);
  --neutral-600: oklch(0.40 0.015 260);
  --neutral-700: oklch(0.32 0.015 260);
  --neutral-800: oklch(0.22 0.015 260);
  --neutral-850: oklch(0.18 0.013 260); /* interpolated */
  --neutral-900: oklch(0.15 0.015 260);
  --neutral-950: oklch(0.10 0.010 260);

  /* ═══ SEMANTIC ACCENT PRIMITIVES ═══ */
  --success-50:  oklch(0.97 0.05  145);
  --success-400: oklch(0.72 0.17  145);
  --success-600: oklch(0.55 0.17  145);
  --success-900: oklch(0.20 0.08  145);

  --warning-50:  oklch(0.97 0.05   65);
  --warning-400: oklch(0.78 0.17   65);
  --warning-600: oklch(0.55 0.17   65);
  --warning-900: oklch(0.20 0.08   65);

  --danger-50:   oklch(0.97 0.05   25);
  --danger-400:  oklch(0.65 0.22   25);
  --danger-600:  oklch(0.50 0.22   25);
  --danger-700:  oklch(0.42 0.20   25);
  --danger-900:  oklch(0.18 0.08   25);

  --info-50:     oklch(0.97 0.04  200);
  --info-400:    oklch(0.68 0.13  200);
  --info-600:    oklch(0.48 0.13  200);

  /* ═══ SEMANTIC LAYER — LIGHT MODE ═══ */
  --text-primary:    var(--neutral-900);
  --text-secondary:  var(--neutral-600);
  --text-muted:      var(--neutral-400);
  --text-on-accent:  var(--neutral-0);
  --text-danger:     var(--danger-600);
  --text-success:    var(--success-600);
  --text-warning:    var(--warning-600);
  --text-link:       var(--brand-blue-600);

  --surface-canvas:  var(--neutral-0);
  --surface-raised:  var(--neutral-50);
  --surface-sunken:  var(--neutral-100);
  --surface-accent:  var(--brand-blue-50);
  --surface-danger:  var(--danger-50);
  --surface-success: var(--success-50);
  --surface-warning: var(--warning-50);
  --surface-info:    var(--info-50);

  --border-subtle:   var(--neutral-200);
  --border-strong:   var(--neutral-300);
  --border-focus:    var(--brand-blue-500);

  --action-primary:           var(--brand-blue-600);
  --action-primary-hover:     var(--brand-blue-700);
  --action-primary-active:    var(--brand-blue-800);
  --action-primary-disabled:  var(--neutral-300);
  --action-secondary:         var(--neutral-100);
  --action-secondary-hover:   var(--neutral-200);
  --action-danger:            var(--danger-600);
  --action-danger-hover:      var(--danger-700);
}

/* ═══ SEMANTIC LAYER — DARK MODE ═══ */
[data-theme="dark"] {
  --text-primary:   var(--neutral-50);
  --text-secondary: var(--neutral-400);
  --text-muted:     var(--neutral-600);
  --text-link:      var(--brand-blue-400);

  --surface-canvas: var(--neutral-950);
  --surface-raised: var(--neutral-900);
  --surface-sunken: oklch(0.08 0.008 260);
  --surface-accent: var(--brand-blue-900);

  --border-subtle:  var(--neutral-800);
  --border-strong:  var(--neutral-700);
  --border-focus:   var(--brand-blue-400);

  --action-primary:          var(--brand-blue-400);
  --action-primary-hover:    var(--brand-blue-300);
  --action-primary-active:   var(--brand-blue-200);
  --action-primary-disabled: var(--neutral-700);
}
```

---

## 2. Typography Token Declarations

```css
/* ═══ TYPOGRAPHY ═══ */
/* Family imports */
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&display=swap');

:root {
  --font-sans: 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
  --font-mono: 'IBM Plex Mono', 'Cascadia Code', 'Fira Code', monospace;

  /* Scale (1.125 major second) */
  --type-caption:   0.694rem; /* 11px */
  --type-small:     0.778rem; /* 12px */
  --type-body:      1.000rem; /* 16px */
  --type-lead:      1.125rem; /* 18px */
  --type-h5:        1.266rem; /* 20px */
  --type-h4:        1.424rem; /* 23px */
  --type-h3:        1.602rem; /* 26px */
  --type-h2:        1.802rem; /* 29px */
  --type-h1:        2.027rem; /* 32px */
  --type-display:   2.281rem; /* 36px */
  --type-mono-sm:   0.778rem; /* 12px */
  --type-mono:      1.000rem; /* 16px */
  --type-mono-lg:   1.125rem; /* 18px */

  /* Line heights */
  --lh-caption: 1.50;
  --lh-body:    1.55;
  --lh-lead:    1.55;
  --lh-h5:      1.35;
  --lh-h4:      1.30;
  --lh-h3:      1.25;
  --lh-h2:      1.20;
  --lh-h1:      1.15;
  --lh-display: 1.10;
  --lh-mono:    1.50;
}

/* Tabular numerals — apply to all data cells */
.tabular-nums,
.stat-value,
td[data-type="number"],
td[data-type="timestamp"] {
  font-variant-numeric: tabular-nums;
}
```

---

## 3. Spacing Tokens

```css
:root {
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;
}
```

---

## 4. Radius Tokens

```css
:root {
  --r-none: 0px;
  --r-xs:   2px;
  --r-sm:   4px;
  --r-md:   6px;
  --r-lg:   8px;
  --r-xl:   12px;
  --r-full: 9999px;
}
```

---

## 5. Elevation Tokens

```css
:root {
  --elevation-resting: 0 1px 2px oklch(0 0 0 / 0.08);
  --elevation-raised:  0 4px 8px oklch(0 0 0 / 0.10),
                       0 1px 2px oklch(0 0 0 / 0.08);
  --elevation-floating:0 8px 24px oklch(0 0 0 / 0.14),
                       0 2px 6px  oklch(0 0 0 / 0.10);
}
```

---

## 6. Motion Tokens

```css
:root {
  --ease-standard:  cubic-bezier(0.4, 0, 0.2, 1);
  --ease-entry:     cubic-bezier(0, 0, 0.2, 1);
  --ease-exit:      cubic-bezier(0.4, 0, 1, 1);

  --duration-micro:    100ms;  /* 80–120ms range */
  --duration-standard: 175ms;  /* 150–200ms range */
  --duration-emphasis: 275ms;  /* 250–300ms — modal/drawer only */
}

/* Reduced motion override */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration:       0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration:      0.01ms !important;
    scroll-behavior:          auto !important;
  }
}
```

---

## 7. Token Application Map (Component → Token)

| Component | Background | Border | Text | Focus ring |
|---|---|---|---|---|
| `<Button primary>` | `action-primary` | none | `text-on-accent` | `border-focus` 2px offset-2 |
| `<Button secondary>` | `action-secondary` | `border-subtle` | `text-primary` | `border-focus` 2px offset-2 |
| `<Button danger>` | `action-danger` | none | `text-on-accent` | `danger-600` 2px offset-2 |
| `<TextInput>` | `surface-raised` | `border-subtle` | `text-primary` | `border-focus` 2px |
| `<TextInput error>` | `surface-raised` | `danger-600` | `text-primary` | `danger-600` 2px |
| `<Badge status: healthy>` | `surface-success` | none | `text-success` | — |
| `<Badge status: degraded>` | `surface-warning` | none | `text-warning` | — |
| `<Badge status: offline>` | `surface-danger` | none | `text-danger` | — |
| `<NavItem active>` | `surface-accent` | `brand-blue-500` left 2px | `text-link` | `border-focus` 2px |
| `<TopBar>` | `neutral-900` (dark) | `border-subtle` bottom 1px | `text-primary` | — |
| `<Sidebar>` | `neutral-900` (dark) | `border-subtle` right 1px | `text-secondary` | — |
| `<Table th>` | `surface-sunken` | `border-strong` bottom 1px | `text-secondary` | — |
| `<Table td>` | `surface-canvas` | `border-subtle` bottom 1px | `text-primary` | — |
| `<Card>` | `surface-raised` | `border-subtle` | `text-primary` | — |
| `<Modal>` | `surface-raised` | none | `text-primary` | — |
| `<Alert danger>` | `surface-danger` | `danger-600` left 4px | `text-danger` | — |
| `<Alert success>` | `surface-success` | `success-600` left 4px | `text-success` | — |
| `<CodeViewer>` | `surface-sunken` | `border-subtle` | `brand-blue-400` (dark mode) | — |
| `<Skeleton>` | `neutral-800` | none | — | — |
