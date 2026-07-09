---
name: probe-user
description: Interview the user about a plan or design, run a gap-elicitation protocol, OR confirm a structured decision (coverage validation, inferred-item review) — all via AskUserQuestion. WHEN: "probe me", "probe user", "stress-test my plan", "let's brainstorm", workflow detects input gaps, OR a workflow needs structured Confirm/Adjust/Reject/Skip decisions on a generated artifact.
license: MIT
metadata:
  author: KANINI
  version: 1.1.0
---

## Rendering Contract (applies to all three modes)

Prefer the host's `AskUserQuestion` tool for rendering every question. The tool enforces one-question-at-a-time structure at the schema level — the model cannot batch. Markdown fallback is used only when `AskUserQuestion` is unavailable.

**Hard rules — violating any of these is a contract violation:**

- **One question per turn.** Never render a second question in the same turn. Stop output after the question block and wait for human input.
- **Exactly 3 concrete options + 1 Custom = 4 total.** Never more. Never fewer. *Exception:* Mode 1 open-discovery first turn — see Mode 1 section.
- **The first option is the recommended choice** (tagged `*recommended*`).
- **The second and third options are material alternatives** — distinct enough that picking between them changes downstream output.
- **The fourth option is always `Custom: _enter your own answer_`** — a free-form escape hatch.
- **If no genuine third alternative exists, slot (c) becomes `Defer — decide later`.** Never pad with filler; never collapse to 2+Custom.
- **Never present the gap detection table to the human.** The table is internal scaffolding for YOUR detection logic only.

## Mode 1 — Open-Ended Interview

Interview the user relentlessly until the **caller-supplied goal** is reached. The caller provides:

- **`$INTERVIEW_GOAL`** — one sentence describing what "done" looks like for this interview (e.g. "every business problem has a measurable success criterion", "every architectural decision has a confirmed driver and trade-off", "every sprint item has an owner and acceptance condition").
- **`$BRANCHES`** — the set of topics the caller wants covered (a list, table, or tree). The skill treats these as a *map*, not a fixed sequence.

If the caller does not supply `$INTERVIEW_GOAL`, default to: *"every branch in `$BRANCHES` has concrete, decision-ready answers — no vague, contradictory, or unresolved items remain"*.

### Universal drill discipline (Mode 1 questions and Mode 2 per-gap turns)

- **Drill, don't skim.** Vague answers ("users", "soon", "better", "robust") trigger a tighter follow-up. Stay on the topic until the answer is **decision-ready** — the caller's next step could act on it without further clarification. No question cap.
- **Self-check after ~5 follow-ups on the same topic.** If you're confirming rather than gaining new information, mark decision-ready and advance.

### Mode 1 — Open-discovery, goal-state, cross-branch steering

- **First turn is free-text.** Opener questions with no prior context to ground three alternatives bypass the 4-option contract — ask once, accept whatever the human says. The 4-option format applies to follow-ups once context exists.
- **Track goal-state per branch** (Open / Decision-ready / Confirmed). Mode 1 exits only when `$INTERVIEW_GOAL` holds across all in-scope branches.
- **Steer across branches.** If an answer exposes a gap in another branch (new actor, new constraint, contradiction with earlier scope), jump to it, resolve, return. Do not enforce linear order at the cost of unresolved cross-branch contradictions.
- **Stop:** goal reached AND information gain ≈ 0, OR human override (`enough` / `skip all` / `wrap up`). On override, return Open branches to the caller.

### Mode 2 — Cross-gap steering

Mode 2 callers do not supply `$INTERVIEW_GOAL` / `$BRANCHES`; the gap detection table and severity classification are the equivalent. If resolving one gap exposes a new gap, append it to the active queue in severity order — do not drop it.

### Markdown fallback format

```text
[Question text]

  (a) [Recommended answer] *recommended*
  (b) [Material alternative based on domain context]
  (c) [Second material alternative OR "Defer — decide later"]
  (d) Custom: _enter your own answer_
```

### Response processing

- **Letter selection** (e.g., "a") → Record the selected option.
- **Custom text** → Record verbatim.
- **"skip"** → Move to next question/branch.

---

## Mode 2 — Gap Elicitation Protocol

Used by workflow prompts that detect gaps in their input. The calling workflow provides a **gap detection table** (workflow-specific categories and detection signals). This protocol governs how detected gaps are classified, presented, and resolved.

### Severity Classification

Assign each detected gap one severity:

| Severity | Definition |
|---|---|
| `BLOCKING` | Analysis cannot produce reliable output without this (e.g., no actors identified, no scope boundary, no quality attributes). |
| `IMPORTANT` | Analysis can proceed but will require significant inference (e.g., no success criteria, no deployment constraints). |
| `NICE-TO-HAVE` | Analysis can infer reasonable defaults (e.g., standard error handling patterns, common responsive breakpoints). |

If zero gaps detected → skip elicitation. Proceed to the next workflow step.

### Severity-first ordering

Process gaps strictly in this order: all `BLOCKING` first, then `IMPORTANT`, then `NICE-TO-HAVE`. After all `BLOCKING` gaps are resolved, announce the transition explicitly and offer an opt-out:

> BLOCKING gaps resolved. N IMPORTANT gaps follow — (a) proceed one at a time, (b) skip all to Inferred Review, (c) defer all to a later revision, (d) Custom.

Same transition announcement applies between `IMPORTANT` and `NICE-TO-HAVE`.

### Presentation Format

Present gaps one at a time using the radio-selection format below, regardless of severity.

1. Present gap inventory summary: total count by severity.

2. Present each gap one at a time:

   ```text
   Gap [current]/[total] ([severity]):

   [Gap category]: [specific description of what is missing]

     (a) [Recommended resolution based on domain context, codebase exploration, or industry standards] *recommended*
     (b) [Material alternative resolution]
     (c) [Second material alternative OR "Defer — mark unresolved, continue workflow"]
     (d) Custom: _enter your own answer_
   ```

   Commands accepted alongside the 4 options:
   - `skip` → same as (c) Defer. Marks this gap unresolved; continues to next gap.
   - `skip all` → defers this and all remaining gaps. Exit the loop.

   Wait for the human's response before presenting the next gap.

### Response Processing

- **(a)/(b) or named option** → Record selected option. Tag as `[SOURCE:INPUT]`.
- **(c) Defer** or `skip` command → Log as unresolved. Downstream inference tagged `[SOURCE:INFERRED]` with `Basis: "Unresolved during elicitation."` Surfaces in the workflow's Inferred Requirement Review step.
- **(d) Custom** or free text → Record verbatim. Tag as `[SOURCE:INPUT]`.
- **`skip all`** → All remaining gaps logged as unresolved. Exit loop.

### Output

Store resolved answers as `$ELICITATION_ADDENDUM`. Append to the workflow's resolved input before the next analysis step. Addendum fills gaps — does not override explicit input statements.

---

## Mode 3 — Decision Confirmation

Structured decisions on generated artifacts. Replaces ad-hoc `Confirm / Flag issues?` and `Accept / Adjust / Reject / Skip?` prompts.

### Shapes

| Shape | Use for | Caller-supplied fields |
|---|---|---|
| `coverage_validation` | Confirm planning inventory before generation | `inventory_table`, `artifact_kind` |
| `inferred_batch_intake` | One-shot tiered triage opening the inferred-review loop | `total_count`, `low_count`, `medium_count`, `high_count` |
| `inferred_review` | Review one `[SOURCE:INFERRED]` item | `item_id`, `item_text`, `basis`, `current_index`, `total_count`, `confidence` (HIGH\|MEDIUM\|LOW) |

Confidence (caller-derived from `Basis:`): explicit rule/external evidence → HIGH; domain-standard inference → MEDIUM; speculative/thin → LOW.

### `coverage_validation` (opt-in — skip when self-checks pass)

Skip entirely when the inventory has: zero orphan FR↔UC links, every Step 3 module represented, no `[UNCLEAR]` rows, item count in template's expected band. Emit a non-blocking console notice and proceed. Invoke only when the agent flags low confidence.

```text
Planned [artifact_kind] coverage shown above. Any issues?

  (a) Confirm — proceed to generation *recommended*
  (b) Flag misscoped items (too broad, too narrow, wrong module/category)
  (c) Flag missing modules or functional areas
  (d) Custom: _enter your own answer_
```

- (a) → proceed. (b)/(c) → caller asks one follow-up for specifics, adjusts inventory, loops back to the affected analysis phase only. (d) → caller interprets.

### `inferred_batch_intake` (one upfront pause; collapses N into 1)

```text
[total_count] inferred items detected ([low_count] LOW, [medium_count] MEDIUM, [high_count] HIGH confidence). Review depth?

  (a) Review LOW + MEDIUM ([low_count]+[medium_count]) *recommended*
  (b) Review only LOW ([low_count])
  (c) Review all [total_count] one-by-one
  (d) Custom: _enter your own answer_ (e.g., "skip review", "specific IDs")
```

- (a) → loop over LOW + MEDIUM; HIGH auto-flipped to `[SOURCE:INPUT]`, no ledger write. **Default for general use** — surfaces anything not strongly grounded.
- (b) → loop over LOW only; MEDIUM + HIGH auto-flipped to `[SOURCE:INPUT]`.
- (c) → loop over all.
- (d) → caller parses free text. `"skip review"` → exit; all stay `[SOURCE:INFERRED]`.

### `inferred_review` (per-item)

```text
Inferred [artifact_kind] Review ([current_index]/[total_count], [confidence] confidence):

[item_id]: [SOURCE:INFERRED] [item_text]
Basis: [basis]

  (a) Accept — confirm as [SOURCE:INPUT] *recommended*
  (b) Adjust — provide replacement text in next turn
  (c) Reject — remove from artifact, log to signal ledger
  (d) Custom: _enter your own answer_
```

- (a) → flip tag to `[SOURCE:INPUT]`.
- (b) → caller asks "What should it be?" next turn; updates text, flips tag, logs CORRECTED.
- (c) → remove item, log REJECTED with reason (or "Not in scope").
- (d) → free text; clarify in one follow-up if ambiguous.
- Commands: `skip` = leave as `[SOURCE:INFERRED]`, advance. `skip all` = exit loop; remaining stay `[SOURCE:INFERRED]`.

---

## Anti-patterns (contract violations)

The following behaviors are explicit contract violations. If you are about to do any of these, stop and re-enter the protocol.

- **Presenting the gap detection table to the human.** The table is internal scaffolding for YOUR detection; the human sees one gap at a time.
- **Batching.** Rendering two or more questions or gaps in one turn.
- **More than four options.** Including Custom, never exceed four.
- **Fewer than four options.** Always render (a), (b), (c), and (d)-Custom. If a third genuine alternative does not exist, (c) is `Defer — decide later`.
- **Padding with filler.** Inventing a third option that duplicates (a) or (b) in different words, or offering an implausible option just to reach three. Use `Defer` instead.
- **Nested sub-questions inside option text.** Example of what NOT to do: `(a) Use React — do you want TypeScript too?`. Sub-questions are follow-ups asked in a separate turn after the response.
- **Restating the protocol to the human.** The protocol is internal. The human only sees: gap counter, gap description, four options, a prompt.

## Error Handling

| Error | Message | Remediation |
|---|---|---|
| AskUserQuestion unavailable | (silent) | Fall back to markdown format per Rendering Contract |
| No genuine third alternative | — | Slot (c) becomes "Defer — decide later" |
| User sends free text instead of letter | — | Record verbatim as Custom; tag `[SOURCE:INPUT]` |
| Zero gaps detected (Mode 2) | — | Skip elicitation; proceed to next workflow step |
