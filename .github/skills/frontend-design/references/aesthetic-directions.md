---
name: aesthetic-directions
description: Seven aesthetic directions with defining traits, typography character, color system character, motion personality, precedents, and anti-uses. Referenced by /frontend-design direction.
---

A direction is a binding commitment. "Modern and clean" is not a direction; "editorial" is. Pick one. Do not blend.

---

## 1. Minimalist
- **Defining traits:** reductive composition, confident whitespace, one hero element per view, no decoration that doesn't earn its place.
- **Typography:** one family, two weights max, wide tracking on display. Swiss grotesque or humanist sans.
- **Color:** near-monochrome. One accent at most. Black and bone white over pure black/white.
- **Motion:** near-invisible. Entry fades, no flourish.
- **Precedents:** Linear, Vercel docs, Jony-era iOS system apps, Kinfolk magazine.
- **Anti-uses:** data-heavy dashboards that need differentiation; entertainment products that need to feel alive; consumer retail.

## 2. Editorial
- **Defining traits:** magazine hierarchy, generous vertical rhythm, deliberate pull-quotes, strong serif voice, image-forward.
- **Typography:** display serif + refined body serif or humanist sans. Large size jumps. Drop caps permitted.
- **Color:** warm paper neutrals, a single ink accent, seasonal secondaries.
- **Motion:** scroll-linked reveals, parallax used sparingly, no bouncing.
- **Precedents:** The New Yorker, The Pudding, Stripe Press, Readymag case studies.
- **Anti-uses:** transactional CRUD apps; high-density admin tools.

## 3. Brutalist
- **Defining traits:** raw grid, visible structure, type as architecture, jarring juxtapositions, monospace fragments, disregard for conventional spacing harmonies.
- **Typography:** monospace or neo-grotesque in block sizes. System-font stacks deliberately exposed.
- **Color:** high-contrast pairs — often pure black on safety colors (fire red, highlighter yellow).
- **Motion:** instant, no easing, or dramatic overshoot.
- **Precedents:** Bloomberg Businessweek covers, Are.na, Gumroad circa 2020, Balenciaga.com.
- **Anti-uses:** medical, financial, or trust-critical workflows; accessibility-sensitive audiences without careful WCAG work.

## 4. Retro-futuristic
- **Defining traits:** nostalgic borrowings from 70s/80s/90s computing, CRT artifacts, grid overlays, pixel-perfect geometry played against modern layout.
- **Typography:** variable-width monospace, geometric sans with a retro kink (Space Grotesk is overused — prefer IBM Plex Mono, Berkeley Mono, Departure Mono).
- **Color:** phosphor green, amber, high-saturation magenta, deep navy. Dark mode as the default.
- **Motion:** scanlines, typewriter reveals, deliberate CRT flicker.
- **Precedents:** Teenage Engineering, Rabbit R1, Arc Browser release films, Berghain-era Detroit techno labels.
- **Anti-uses:** children's products; luxury; anything requiring "timeless."

## 5. Maximalist
- **Defining traits:** density as a feature, layered ornament, pattern over plain, clash as harmony, confidence through excess.
- **Typography:** multiple families coexisting; decorative display faces; hand-lettering accents.
- **Color:** saturated palettes, 5+ hues, pattern fills, textures.
- **Motion:** orchestrated, layered, reveals on reveals.
- **Precedents:** Glossier Play, MSCHF product drops, Are.na channels at full density, Wes Anderson title cards.
- **Anti-uses:** enterprise tools; anything requiring calm focus.

## 6. Utilitarian
- **Defining traits:** information density prioritized, no decoration, tight vertical rhythm, keyboard-first, deliberately plain.
- **Typography:** one grotesque sans + one monospace. Small sizes. Tabular numerals mandatory.
- **Color:** cool neutrals, semantic-only accents (success, warning, error). No brand color in the body.
- **Motion:** none outside state feedback.
- **Precedents:** Bloomberg Terminal, Sentry, Grafana, PostHog, early 37signals.
- **Anti-uses:** marketing surfaces; onboarding for non-technical audiences.

## 7. Expressive
- **Defining traits:** personality-forward, hand-drawn or hand-authored feel, playful illustration integrated with UI, soft geometry, non-rigid grid.
- **Typography:** rounded or humanist display + handwritten or custom accent. Body kept readable.
- **Color:** warm saturated palette, pastel support, intentional gradients (not the purple-blue default).
- **Motion:** playful, physics-aware, delightful on success states.
- **Precedents:** Duolingo, Notion early era, Slack marketing site, Figma Community pages.
- **Anti-uses:** somber contexts (bereavement, health crisis); regulated compliance surfaces.

---

## Selection heuristic
1. Name the primary persona's context in one word (analyst, reader, builder, player, caretaker, executive, fan).
2. Name the product's required emotional register (calm, urgent, delighted, rigorous, reverent, irreverent).
3. Match persona + register against the direction table. Pick the single best fit. If two directions tie, prefer the one with the more honest anti-brief for this product.
