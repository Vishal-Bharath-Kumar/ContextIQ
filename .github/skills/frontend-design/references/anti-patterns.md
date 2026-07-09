---
name: anti-patterns
description: Hard bans (with detection regexes), soft bans, and paired replacements. Consumed by challenge-artifact as an extended rule when reviewing figma_spec/designsystem/wireframe artifacts; regexes also inlined into create-figma-spec and generate-wireframe quality gates.
---

Every entry: **symptom → why it reads generic → replacement → detection regex**.

Detection regexes run against the target artifact (HTML, CSS, markdown). Count > 0 on a hard ban = FAIL. Multiline scanning where noted.

---

## Hard bans (FAIL the AI Slop Test)

### 1. Gradient text on primary content
- **Symptom:** `background: linear-gradient(...); -webkit-background-clip: text; color: transparent;` on H1, CTAs, or body.
- **Why:** It is the most overused AI-generation tell. It often fails contrast. It signals "I couldn't commit to a color."
- **Replacement:** one confident solid color, expressing the direction. If the direction genuinely needs a gradient, apply it to a background shape or ornament, not the glyph fill.
- **Detection:** `background-clip:\s*text` OR `-webkit-background-clip:\s*text`

### 2. Glassmorphism as decoration
- **Symptom:** `backdrop-filter: blur(...)` with translucent white/dark background on surfaces that have no content behind them.
- **Why:** blur only reads as design when there is actual content to blur. Otherwise it is costume.
- **Replacement:** solid surface with intentional elevation. Reserve blur for true overlays above varied content (modals over a busy canvas).
- **Detection:** `backdrop-filter:\s*blur` (manual review for "has content behind it"; count as finding, classify in review).

### 3. Colored left/right borders > 1px on cards, alerts, list items
- **Symptom:** 3–6px solid color strip on the leading edge of every card or alert.
- **Why:** Bootstrap-era alert styling, now a default for LLM-generated UIs.
- **Replacement:** express status via icon + text color + a subtle tinted background; or a 1px border in the same semantic color; never a thick color strip.
- **Detection:** `border-(left|right):\s*[2-9]\d*px` OR `border-inline-(start|end):\s*[2-9]\d*px`

### 4. Default font as the product's sole voice
- **Symptom:** Inter, DM Sans, Roboto, Poppins, or Montserrat used as **both** display and body (i.e., the product's only typeface).
- **Why:** using one of these everywhere means no typographic choice was made. Any of them as body alongside a distinctive display is fine.
- **Replacement:** pair the body family with a distinctive display face from the direction's pairing table in `color-typography-systems.md`.
- **Detection:** count occurrences of `font-family:[^;]*(Inter|DM Sans|Roboto|Poppins|Montserrat)` — if the same family is the only one in the file, FAIL. Two or more distinct families → PASS.

### 5. Unjustified purple-to-blue gradient
- **Symptom:** `linear-gradient(135deg, #6366F1, #3B82F6)` or any near-equivalent on hero, CTA, or primary surface.
- **Why:** the single most recognizable AI-generation aesthetic.
- **Replacement:** a solid color that expresses the direction; or a multi-stop gradient with at least one warm hue; or a non-linear gradient (radial, conic) if ornament is warranted.
- **Detection:** `linear-gradient\([^)]*#?(6366[fF]1|818[cC][fF]8|[Aa]78[Bb][Ff][Aa]|7[Cc]3[Aa][Ee][Dd])[^)]*#?(3[Bb]82[Ff]6|60[Aa]5[Ff][Aa]|2563[Ee][Bb])`

### 6. Hex literals in the designsystem primitive consumer layer
- **Symptom:** `color: #111827;` used directly in the designsystem artifact's semantic or component layer (should reference primitive tokens by name).
- **Why:** within the designsystem artifact, the whole point of layering is name-based reference.
- **Replacement:** semantic/component layer references primitive by token name; consumer wireframes/Tailwind projects are NOT subject to this ban.
- **Detection:** scoped to `$DESIGNSYSTEM_OUTPUT_PATH` only. Regex `#[0-9a-fA-F]{6}` outside a fenced block labelled "primitive".

### 7. Lorem ipsum in hi-fi artifacts
- **Symptom:** placeholder Latin text in any hi-fi wireframe or mockup.
- **Why:** hi-fi requires realistic content; lorem ipsum defeats the entire purpose.
- **Replacement:** inline realistic content from `sample-data.json`.
- **Detection:** `(?i)lorem ipsum|dolor sit amet|consectetur adipiscing`

### 8. Animating layout properties for state changes
- **Symptom:** `transition: width 200ms;` on hover; animating `top`/`left`/`margin`.
- **Why:** triggers layout + paint + composite, janks on any non-trivial page.
- **Replacement:** animate `transform` and `opacity`. Use `will-change` only on elements that actually change.
- **Detection:** `transition(-property)?:[^;]*(width|height|top|left|right|bottom|margin)\b`

---

## Soft bans (flag but do not FAIL; require explicit justification to ship)

### 9. All-capitalized body labels
- **Symptom:** `text-transform: uppercase` on labels longer than a single word.
- **Why:** hurts readability without adding hierarchy most of the time.
- **Justified:** short eyebrow labels in editorial layouts; brutalist direction by design.

### 10. Single accent hue across a whole product
- **Symptom:** every CTA, link, focus ring, and highlight uses the one brand color.
- **Why:** the product loses semantic differentiation — primary actions look the same as warnings.
- **Justified:** minimalist direction with deliberate restraint.

### 11. Iconography pulled from multiple libraries
- **Symptom:** Heroicons, Lucide, and Font Awesome all present.
- **Why:** stroke weights and corner treatments clash.
- **Justified:** never. Fix it.

### 12. Centered-everything layouts
- **Symptom:** hero, feature blocks, testimonials, footer — all center-aligned.
- **Why:** reads as a template.
- **Justified:** minimalist or expressive direction with deliberate vertical rhythm.

### 13. Skeuomorphic drop shadows on flat UI
- **Symptom:** `box-shadow: 0 10px 40px rgba(0,0,0,0.2)` on a card that otherwise looks flat.
- **Why:** disproportionate elevation reads amateur.
- **Replacement:** three-step elevation scale tied to semantic use (resting, raised, floating).

### 14. Emoji as iconography
- **Symptom:** 🚀, ✨, 💡 as bullet markers or feature icons.
- **Why:** clashes with real iconography and platform rendering varies wildly.
- **Justified:** expressive direction, consumer-casual contexts.

### 15. Gradient borders ("retro gradient card")
- **Symptom:** `border-image: linear-gradient(...)` on every card.
- **Why:** overused tutorial pattern.
- **Justified:** a single hero element per page, maximalist or retro-futuristic direction only.

---

## Critique output template

Run every hard-ban Detection regex against the target artifact. Emit per-pattern counts; no self-graded verdict.

```
Frontend-design critique — artifact: [path]
Direction declared: [yes | no]

Hard-ban scan (target: 0 on each)
| # | Pattern | Regex | Matches | Locations |
|---|---------|-------|---------|-----------|
| 1 | Gradient text | background-clip:\s*text | [count] | [file:line list] |
| ... (all 8) |

Soft bans (manual review)
| # | Pattern | Location | Justified per direction? |
|---|---------|----------|--------------------------|

Totals: hard_bans_total=[sum], soft_bans_flagged=[sum]
Gate: hard_bans_total == 0 → PASS; else FAIL.
```
