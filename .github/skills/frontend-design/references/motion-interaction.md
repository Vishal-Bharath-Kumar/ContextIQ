---
name: motion-interaction
description: Motion intent, easing, timing, reduced-motion compliance, and interaction-state expression. Complements the required-states table in rules/ui-ux-design-standards.md.
---

## Principle

Motion exists to make state changes legible. It is not decoration. Every animation must answer a question:
- Where did it come from?
- What changed?
- Where did it go?

If the animation answers none of these, remove it.

---

## When to animate

- **Entry and exit of mounted elements** (modals, drawers, toasts, popovers).
- **State transitions on controls** (button press, input focus, toggle flip).
- **Confirmation of success** (inline check, subtle scale).
- **Error surfacing** (shake on form submit error — subtle, one cycle).
- **Loading boundaries** (skeletons to content, spinners for local async).

## When not to animate

- Scrolling (the browser already does this well).
- Layout properties (`width`, `height`, `top`, `left`, `margin`) — animate `transform` and `opacity` instead.
- Decorative hover on every element (animate only what matters).
- Page load ceremonies longer than 400ms total.

---

## Easing defaults

- Standard (most state changes): `cubic-bezier(0.4, 0, 0.2, 1)` — material-standard ease-in-out.
- Entry (something appearing): `cubic-bezier(0, 0, 0.2, 1)` — ease-out. Decelerate into place.
- Exit (something leaving): `cubic-bezier(0.4, 0, 1, 1)` — ease-in. Accelerate away.
- Emphasized (delighters only): `cubic-bezier(0.2, 0, 0, 1)` — exponential; dramatic but controlled.

Avoid linear easing except for scroll-linked effects. Avoid bouncy spring easings unless the chosen direction is `expressive`.

---

## Timing windows

- Micro (state feedback): 80–150ms.
- Standard (entry/exit of small UI): 150–250ms.
- Emphasized (modals, drawers, major transitions): 250–350ms.
- Nothing should exceed 400ms unless it is an orchestrated sequence with explicit rationale.

Faster is almost always better. If in doubt, halve the duration.

---

## Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Exception: cross-fades for state legibility may retain a very short duration (≤80ms), because an instant pop can itself be disorienting. Favor opacity over motion under reduced-motion.

---

## Interaction state expression

The *required* component states (default, hover, focus, active, disabled, loading, error) are defined in [ui-ux-design-standards.md](../../../rules/ui-ux-design-standards.md). This reference governs **how motion expresses the transition between them**, not what states exist.

| State transition | Expression |
|---|---|
| default → hover | background/border color shift over 80–120ms; no size change |
| default → focus | focus ring appearance over 80ms, solid not animated |
| default → active (press) | instant scale 0.97–0.98 or color shift; restore on release |
| default → disabled | opacity shift only; no geometry change |
| default → loading | controls remain in place; spinner or skeleton replaces content within the same bounds |
| error | one-cycle horizontal shake on submit: ±4px translateX, 3 cycles, 60ms each |

**Never** animate `width`, `height`, or `border-radius` between states. Use `transform: scale()` for size and separate the focus ring into a pseudo-element that scales with the host.

---

## Scroll-linked motion

Permitted for editorial direction. Rules:
- Effect must be continuous (1:1 with scroll progress), not triggered.
- Parallax depth ≤ 0.3 (background moves at 0.3× the foreground's rate — deeper than that induces motion sickness for some users).
- `scroll-behavior: smooth` is global default only for in-page anchor navigation; disable for long pages.

---

## Orchestration

Stagger related elements entering together: 40–60ms delay between siblings, decay of 0.85. More than 8 elements in a stagger is over-orchestrated.
