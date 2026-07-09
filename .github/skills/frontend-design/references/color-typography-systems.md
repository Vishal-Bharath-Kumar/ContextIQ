---
name: color-typography-systems
description: OKLCH color construction, semantic token layering, modular typography scales, and display/body pairing heuristics. Consumed inline by create-figma-spec Phase 7.2.
---

## Color: OKLCH-first construction

Work in OKLCH, not HSL or hex. OKLCH is perceptually uniform — two colors with the same `L` read as equally bright. HSL breaks this across hues.

### Primitive layer

A primitive is a raw value. Name primitives by family + step (`blue-500`, not `brand`).

- Pick one **brand hue** (the anchor chroma). Record it as an OKLCH triple: `oklch(L C H)`.
- Generate a 12-step scale for each hue family used (brand, neutral, and each semantic).
- **Neutrals must be tinted toward the brand hue** with chroma in the range `0.01–0.025 (perceptible warmth, not a stylistic statement)`. Pure gray reads as stock UI; tinted gray reads as a system.
- Light-mode L range: `0.98` (lightest) down to `0.12` (text). Dark-mode L range: `0.08` up to `0.96`. Do not invert; pick independently.

### Semantic layer

A semantic token expresses **intent**, not appearance. Consumers always reference semantic, never primitive.

- `text-primary`, `text-secondary`, `text-muted`, `text-on-accent`
- `surface-canvas`, `surface-raised`, `surface-sunken`, `surface-accent`
- `border-subtle`, `border-strong`, `border-focus`
- `feedback-success`, `feedback-warning`, `feedback-danger`, `feedback-info`
- `action-primary`, `action-primary-hover`, `action-primary-active`, `action-primary-disabled`

Semantic tokens resolve to primitive values. Dark mode is a separate resolution table, not a color flip.

### Component layer (optional)

Where a semantic token is ambiguous for a specific component (e.g. a chip's background differs from a card's), introduce a component-scoped token: `chip-bg-neutral`, `chip-bg-accent`. Component tokens reference semantic tokens.

### Rules

- No hex in any consumer. Hex is allowed only in the primitive table.
- Contrast must hit WCAG AA at minimum (4.5:1 body text, 3:1 large text and UI).
- Accent hue count: 1 brand + up to 2 secondaries. More reads as maximalist — acceptable only if the chosen direction is `maximalist` or `expressive`.

---

## Typography: modular scale + intentional pairing

### Modular scale

Pick one ratio and commit. Common ratios:

| Ratio | Character | Suits |
|---|---|---|
| 1.125 (major second) | tight, newspaper-like | dense UIs, admin tools |
| 1.200 (minor third) | balanced | most product UIs |
| 1.250 (major third) | confident | marketing surfaces, longer-form reading |
| 1.333 (perfect fourth) | dramatic | editorial display, hero-heavy layouts |
| 1.414 (augmented fourth) | theatrical | landing pages with heavy vertical rhythm |

Direction-to-ratio mapping is handled case-by-case in the pairing examples table below; do not treat the ratios as keyed to directions.

Anchor at `1rem` (body). Generate the full scale both directions: `caption`, `small`, `body`, `lead`, `h5`, `h4`, `h3`, `h2`, `h1`, `display`.

### Weights

Use extremes. `100/200` paired with `800/900` reads intentional; `400/600` reads default. If the family does not support extreme weights, pick a different family.

### Display + body pairing

A product needs two families at most. More is either maximalist (allowed) or carelessness (not).

**Pairing heuristics:**
1. High contrast across axis: serif display + grotesque body; geometric display + humanist body; monospace display + serif body.
2. Match x-heights within ~10% so inline mixing reads deliberate.
3. Reject any pairing where both families would be described as "clean" — that is the AI default.

**Worked examples by direction:**

| Direction | Display | Body | Mono (optional) |
|---|---|---|---|
| minimalist | Söhne or ABC Diatype | Söhne or ABC Diatype | ABC Diatype Mono |
| editorial | GT Sectra or Newsreader | Source Serif 4 or Charter | JetBrains Mono |
| brutalist | ABC Monument Grotesk or Neue Haas Grotesk | same, same family | Berkeley Mono |
| retro-futuristic | Departure Mono or IBM Plex Mono | IBM Plex Sans | Berkeley Mono |
| maximalist | PP Editorial New or Migra | Inter Tight or GT Planar | — |
| utilitarian | IBM Plex Sans | IBM Plex Sans | IBM Plex Mono |
| expressive | Bricolage Grotesque or Monument Grotesk Variable | Geist or Figtree | — |

**Never-ship defaults:** Inter everywhere; Fraunces + DM Sans; Space Grotesk + anything; Poppins; Montserrat; Open Sans; Lato.

### Line height

- Body: 1.5–1.6 for grotesques and sans; 1.55–1.7 for serifs.
- Display (h1/h2/display): 1.0–1.15.
- Monospace code blocks: 1.45–1.55.

### Tabular numerals

Enable `font-variant-numeric: tabular-nums` for any column of numbers (tables, stats, financial values). Missing tabular nums is a common AI-slop signal.

---

## Spacing: 4pt scale with semantic tokens

Primitive steps: `0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96`. Values below 4 are permitted only for hairlines.

Semantic tokens:
- `space-inset-*` — padding inside a container (sm/md/lg/xl)
- `space-stack-*` — vertical gap between block-level siblings
- `space-inline-*` — horizontal gap between inline siblings

Use `gap` on flex/grid containers, not margins, for sibling spacing. Margin is reserved for breaking out of containers (rare).

---

## Radius and shadow

- Radius scale: `0, 2, 4, 8, 12, 16, 9999` (full). Pick three for the product; more is noise.
- Shadows in OKLCH too: blend the brand hue at very low chroma into the shadow color so shadows don't read as generic gray blur. Three elevation steps, not five.
