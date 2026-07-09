---
name: ux-heuristics
description: 'Evaluate and improve interface usability using heuristic analysis. WHEN: "usability audit", "UX review", "users are confused", "heuristic evaluation", "form usability", "navigation problems". For visual design fixes, see refactoring-ui; for conversion-focused audits, see cro-methodology.'
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

# UX Heuristics Framework

Practical usability principles for evaluating and improving user interfaces. Based on a fundamental truth: users don't read, they scan. They don't make optimal choices, they satisfice. They don't figure out how things work, they muddle through.

## Quick Reference

| | |
|---|---|
| **Best for** | Heuristic evaluation of interface usability |
| **Frameworks** | Krug's Three Laws · Nielsen's 10 Heuristics · Severity Scale 0–4 |
| **References** | `references/krug-principles.md` · `references/nielsen-heuristics.md` · `references/audit-template.md` · `references/dark-patterns.md` · `references/wcag-checklist.md` · `references/cultural-ux.md` · `references/heuristic-conflicts.md` |

## Core Principle

**"Don't Make Me Think"** - Every page should be self-evident. If something requires thinking, it's a usability problem.

**The foundation:** Users have limited patience and cognitive bandwidth. The best interfaces are invisible -- they let users accomplish goals without ever stopping to wonder "What do I click?" or "Where am I?" Every question mark that pops into a user's head adds to cognitive load and increases the chance they'll leave. Design for scanning, satisficing, and muddling through -- because that's what users actually do.

## Scoring

**Goal: 10/10.** When reviewing or creating user interfaces, rate them 0-10 based on adherence to the principles below. A 10/10 means full alignment with all guidelines; lower scores indicate gaps to address. Always provide the current score and specific improvements needed to reach 10/10.

## Krug's Three Laws of Usability

### 1. Don't Make Me Think
Every question mark in a user's head adds cognitive load. Clever names lose to clear names; plain language beats jargon ("Sign in" not "Access your account portal"). If a label needs explanation, simplify it — don't add a tooltip.

### 2. It Doesn't Matter How Many Clicks
Three mindless confident clicks beat one confusing click. Users abandon when they lose confidence, not when they've clicked too many times. Make each step obvious with breadcrumbs, progress indicators, and descriptive labels.

### 3. Get Rid of Half the Words
Users scan, they don't read. Cut happy-talk, polite fluff ("Please kindly note…"), and instructions nobody reads. "Enter your password to continue" beats any paragraph.

### 4. The Trunk Test
Drop the user on any random page — can they instantly answer: what site is this? what page? what are my options? where am I in the hierarchy? where is search? If not, fix global nav, page titles, and breadcrumbs.

See [references/krug-principles.md](references/krug-principles.md) for the full methodology, product-context tables, copy patterns, and ethical boundaries for each law.

## Nielsen's 10 Usability Heuristics

| # | Heuristic | One-liner |
|---|---|---|
| 1 | Visibility of System Status | Every action needs acknowledgment — loading states, confirmations, skeletons. Silent failures destroy trust. |
| 2 | Match System to Real World | Users' language, not system language. "Sign in" not "Authenticate". Real-world metaphors. |
| 3 | User Control and Freedom | Undo beats "Are you sure?". Every flow needs cancel/exit; soft delete beats permanent. |
| 4 | Consistency and Standards | Same words/styles/behaviors throughout. Follow platform conventions (logo top-left, search top-right). |
| 5 | Error Prevention | Constrain inputs, autocomplete, sensible defaults, unsaved-changes warnings. |
| 6 | Recognition over Recall | Show options, don't require memorization. Breadcrumbs, recent searches, pre-filled fields. |
| 7 | Flexibility and Efficiency | Serve novices and experts. Shortcuts, bulk actions, command palettes. Progressive disclosure. |
| 8 | Aesthetic and Minimalist | Every element earns its place. One primary CTA per page, not five. |
| 9 | Recognize, Diagnose, Recover | Error messages: what happened + why + how to fix. Plain language; never blame the user. |
| 10 | Help and Documentation | Searchable, task-focused, contextual (tooltips, inline hints, guided tours). |

See [references/nielsen-heuristics.md](references/nielsen-heuristics.md) for detailed examples, product applications, copy patterns, and ethical boundaries for all 10 heuristics.

## Severity Rating Scale

When auditing interfaces, rate each issue:

| Severity | Rating | Description | Priority |
|----------|--------|-------------|----------|
| **0** | Not a problem | Disagreement, not usability issue | Ignore |
| **1** | Cosmetic | Minor annoyance, low impact | Fix if time |
| **2** | Minor | Causes delay or frustration | Schedule fix |
| **3** | Major | Significant task failure | Fix soon |
| **4** | Catastrophic | Prevents task completion | Fix immediately |

### Rating Factors

Consider all three:

1. **Frequency:** How often does it occur?
2. **Impact:** How severe when it occurs?
3. **Persistence:** One-time or ongoing problem?

## Common Mistakes

| Mistake | Why It Fails | Fix |
|---------|-------------|------|
| **Mystery meat navigation** | Icons without labels force guessing | Add text labels alongside icons |
| **Too many choices** | Decision paralysis slows users | Reduce to 7 plus/minus 2 items |
| **No "you are here" indicator** | Users feel lost in the hierarchy | Highlight current section in nav and breadcrumbs |
| **No inline validation** | Submit, error, scroll cycle frustrates | Validate on blur with specific messages |
| **Unclear required fields** | Users confused about what's mandatory | Mark optional fields, not required (most fields should be required) |
| **Wall of text** | Nobody reads dense paragraphs | Break up with headings, bullets, whitespace |
| **Jargon in labels** | Users don't speak your internal language | User-test all labels, use plain language |
| **No loading indicators** | Users think the system is broken | Show spinner, progress bar, or skeleton screen |
| **Tiny tap targets** | Mobile users misclick constantly | Minimum 44x44 px touch targets |
| **Hover-only information** | Mobile and keyboard users miss it entirely | Don't hide critical info behind hover states |
| **No undo** | Users afraid to take any action | Provide undo for all non-destructive actions |
| **Poor error messages** | "Invalid input" tells users nothing | Explain what's wrong and how to fix it |
| **Low contrast text** | Unreadable for many users | WCAG AA minimum (4.5:1 contrast ratio) |
| **Inconsistent nav location** | Users can't find navigation | Fixed position, same location on every page |
| **Broken back button** | Fundamental browser contract violated | Never hijack or break browser history |

## Quick Diagnostic

Audit any interface:

| Question | If No | Action |
|----------|-------|--------|
| Can I tell what site/page this is immediately? | Users are lost and disoriented | Add clear logo, page title, and breadcrumbs |
| Is the main action obvious? | Users don't know what to do | Create visual hierarchy, single primary CTA |
| Is the navigation clear? | Users can't find their way | Apply the Trunk Test, add "you are here" indicators |
| Can I find the search? | Users with specific goals are blocked | Add visible search box in header |
| Does the system show me what's happening? | Users lose trust and re-click | Add loading states, confirmations, progress indicators |
| Are error messages helpful? | Users get stuck on errors | Rewrite in plain language with specific fix |
| Can users undo or go back? | Users are afraid to act | Add undo, cancel, and back options everywhere |
| Does it work without hover? | Mobile and keyboard users are excluded | Replace hover-only interactions with visible alternatives |
| Are all interactive elements labeled? | Users guess at icon meanings | Add text labels or descriptive tooltips |
| Does anything make me stop and think "huh?" | Cognitive load is too high | Simplify -- if it needs explanation, redesign it |

## Heuristic Conflicts

Heuristics sometimes contradict each other. When they do:
- **Simplicity vs. Flexibility**: Use progressive disclosure
- **Consistency vs. Context**: Consistent patterns, contextual prominence
- **Efficiency vs. Error Prevention**: Prefer undo over confirmation dialogs
- **Discoverability vs. Minimalism**: Primary actions visible, secondary hidden

See: [references/heuristic-conflicts.md](references/heuristic-conflicts.md) for resolution frameworks.

## Dark Patterns Recognition

Dark patterns violate heuristics deliberately to manipulate users:
- Forced continuity (hard to cancel)
- Roach motel (easy in, hard out)
- Confirmshaming (guilt-based options)
- Hidden costs (surprise fees at checkout)

See: [references/dark-patterns.md](references/dark-patterns.md) for complete taxonomy and ethical alternatives.

## When to Use Each Method

| Method | When | Time | Findings |
|--------|------|------|----------|
| Heuristic evaluation | Before user testing | 1-2 hours | Major violations |
| User testing | After heuristic fixes | 2-4 hours | Real behavior |
| A/B testing | When optimizing | Days-weeks | Statistical validation |
| Analytics review | Ongoing | 30 min | Patterns and problems |

## Reference Files

- [krug-principles.md](references/krug-principles.md): Full Krug methodology, scanning behavior, navigation clarity
- [nielsen-heuristics.md](references/nielsen-heuristics.md): Detailed heuristic explanations with examples
- [audit-template.md](references/audit-template.md): Structured heuristic evaluation template
- [dark-patterns.md](references/dark-patterns.md): Categories, examples, ethical alternatives, regulations
- [wcag-checklist.md](references/wcag-checklist.md): Complete WCAG 2.1 AA checklist, testing tools
- [cultural-ux.md](references/cultural-ux.md): RTL, color meanings, form conventions, localization
- [heuristic-conflicts.md](references/heuristic-conflicts.md): When heuristics contradict, resolution frameworks

## Further Reading

This skill is based on usability principles developed by Steve Krug and Jakob Nielsen:

- [*"Don't Make Me Think, Revisited"*](https://www.amazon.com/Dont-Make-Think-Revisited-Usability/dp/0321965515) by Steve Krug
- [*"Rocket Surgery Made Easy"*](https://www.amazon.com/Rocket-Surgery-Made-Easy-Yourself/dp/0321657292) by Steve Krug (DIY usability testing)
- [*"10 Usability Heuristics for User Interface Design"*](https://www.nngroup.com/articles/ten-usability-heuristics/) by Jakob Nielsen (Nielsen Norman Group)

## Error Handling

| Error | Message | Remediation |
|---|---|---|
| No interface to evaluate | "No target specified" | Request URL, screenshot, or descriptor |
| Severity unclear | — | Apply the Severity Rating Scale (0–4) × frequency × impact × persistence |
| Heuristics conflict | — | See [references/heuristic-conflicts.md](references/heuristic-conflicts.md) |
| Dark pattern suspected | — | See [references/dark-patterns.md](references/dark-patterns.md); surface ethical boundary |

## About the Author

**Steve Krug** is a usability consultant who has been helping companies make their products more intuitive since the 1990s. His book *"Don't Make Me Think"* (first published in 2000, revised 2014) is the most widely read book on web usability and is considered essential reading for anyone involved in designing interfaces. Known for his accessible, humorous writing style and his advocacy for low-cost usability testing, Krug demonstrated that usability doesn't require a lab or a large budget -- just watching a few real users try to accomplish tasks.

**Jakob Nielsen, PhD** is co-founder of the Nielsen Norman Group (NN/g) and is widely regarded as the "king of usability." His 10 Usability Heuristics for User Interface Design, published in 1994, remain the most-used framework for heuristic evaluation worldwide. Nielsen has been called "the guru of Web page usability" by *The New York Times* and has authored numerous influential books on usability engineering. His research-driven approach to interface design helped establish usability as a recognized discipline in software development.
