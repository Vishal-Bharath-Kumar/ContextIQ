---
name: frontend-design
description: Force a single, named aesthetic direction before any token, typography, or layout decision. Owns four modes callers invoke by name. WHEN: "/frontend-design direction", "/frontend-design tokens", "/frontend-design motion", "/frontend-design anti-patterns", choose aesthetic direction, brand personality, derive design tokens, motion personality, scan for AI-slop anti-patterns.
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

## Purpose

PropelIQ authority on the one decision upstream of every visual choice: **which aesthetic direction does this product commit to?** Without a committed direction, tokens, typography, and motion are made case-by-case and converge on generic AI defaults. With a direction, every downstream choice has something to honor or violate.

Compliance constraints (WCAG, required states, fidelity definitions, responsive breakpoints) are owned by `rules/ui-ux-design-standards.md` and `rules/web-accessibility-standards.md`. Token values, motion curves, and the anti-pattern catalog are owned by the reference files below — see the References section for the caller contract.

---

## Mode — `direction`

Invoke as `/frontend-design direction [inputs]`.

**Inputs:** personas, product tone signals, brand references, domain — sourced from the calling workflow's resolved input.

**Process:**
1. Read `references/aesthetic-directions.md` for the closed set of seven directions.
2. Match inputs to exactly one direction. Reject hedged answers ("modern and clean" is not a direction).
3. Produce the four-field output below.

**Output shape:**
```text
Direction: [minimalist | editorial | brutalist | retro-futuristic | maximalist | utilitarian | expressive]
Rationale: [1 paragraph tying direction to personas, tone, and domain]
Precedents: [three named products, sites, or publications]
Anti-brief: [what this product must not resemble]
```

The seven-direction list is closed by design — the value is the forcing function. Do not treat it as "not limited to."

---

## Mode — `tokens`

Invoke as `/frontend-design tokens [direction_output] [optional_brand_overrides]`.

**Inputs:** the Direction output from `direction` mode; optional explicit brand/colour/font constraints from the caller.

**Process:**
1. Read `references/color-typography-systems.md` for OKLCH construction, semantic layering, modular scales, and pairing heuristics.
2. Map the direction to token choices: brand hue + neutral tint, modular ratio, display/body pairing, spacing cadence, radius scale, three-level elevation.
3. Emit the three-field contract below.

**Output shape:**
```text
color_system: brand hue (OKLCH triple), neutral tint rule, semantic token map (text-*, surface-*, border-*, feedback-*, action-*)
typography_system: display/body pair, modular ratio, size scale (caption -> display), weight strategy
spacing_radius_elevation: spacing steps, radius scale, three-level elevation (resting / raised / floating)
```

---

## Mode — `motion`

Invoke as `/frontend-design motion [direction_output]`.

**Inputs:** the Direction output from `direction` mode.

**Process:**
1. Read `references/motion-interaction.md` for easing defaults, timing windows, and reduced-motion compliance.
2. Select easing and timing per the direction's personality (e.g. brutalist keeps micro snappy; expressive permits bouncy springs).
3. Emit the motion personality.

**Output shape:**
```text
motion_personality: easing curves (standard / entry / exit / emphasized), timing windows (micro / standard / emphasized), reduced-motion fallback CSS
```

---

## Mode — `anti-patterns`

Invoke as `/frontend-design anti-patterns [target_paths] [artifact_type]`.

**Inputs:** one or more file or directory paths to scan; `artifact_type` is one of `figma_spec | designsystem | wireframe | mvp_source`. Artifact type governs scoping rules (e.g. the primitive-layer hex ban is scoped to the designsystem artifact only).

**Process:**
1. Read `references/anti-patterns.md` for the hard-ban and soft-ban catalogs and detection regexes.
2. Run every hard-ban detection regex against each target path, honouring scoping rules.
3. Run every soft-ban detection regex; flag matches with replacement and justified-context guidance.
4. Emit the report below.

**Output shape:**
```text
hard_bans: table of { pattern_name, count, offending_sites, replacement_guidance }
soft_bans: table of { pattern_name, count, offending_sites, justified_context }
hard_bans_total: integer  — the quality-gate metric; ship gate is hard_bans_total == 0
soft_bans_total: integer  — informational
```

Skill reports; callers enforce `hard_bans_total == 0` in their quality gates.

---

## References

Consumed internally by this skill's modes. Callers do not read these files directly.

- `references/aesthetic-directions.md` — the seven directions, traits, precedents, anti-uses
- `references/color-typography-systems.md` — OKLCH construction, semantic layering, modular typography scales, pairing examples
- `references/motion-interaction.md` — state-change moments, easing, reduced-motion compliance
- `references/anti-patterns.md` — hard bans, soft bans, detection regexes, replacements

## Error Handling

| Error | Mode | Message | Remediation |
|---|---|---|---|
| Hedged direction | direction | "Input yields no single direction" | Reject; request stronger signals from user |
| No match in closed set | direction | "No match in the seven directions" | Pick nearest; state the violation explicitly |
| Missing inputs | direction | "Insufficient inputs for direction" | Escalate to /probe-user for elicitation |
| Missing direction | tokens / motion | "Direction required" | Invoke /frontend-design direction first; pass its output |
| No target paths | anti-patterns | "No paths to scan" | Caller must provide file or directory paths |
| Unknown artifact_type | anti-patterns | "Unknown artifact_type" | Must be one of figma_spec / designsystem / wireframe / mvp_source |
