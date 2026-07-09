---
name: classify-artifact
description: Classify a PropelIQ artifact by content signals (spec, design, epics, user-story, task, test-plan, model, code, other) and return its upstream dependency chain. Called by workflow steps only — not directly user-invocable. WHEN: workflow references /classify-artifact, needs artifact-type-driven logic, or needs upstream keys for cross-referencing.
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

## Input

`$ARGUMENTS` — the resolved artifact content (already loaded by `/input-resolver`). May also include the artifact key if the user passed one (e.g., `spec`, `design`).

## Classification Logic

Determine artifact type from content signals. Classify by semantic structure, not file format:

| Signal in Content | Classified As |
|---|---|
| Contains requirement IDs (FR-NNN), "MUST"/"SHALL" statements, acceptance criteria, use case specifications (UC-NNN) | `spec` |
| Contains NFR-NNN, DR-NNN, TR-NNN, AIR-NNN, architecture components, technology stack decisions, component diagrams | `design` |
| Contains EP-NNN, epic groupings, requirement-to-epic mappings, business value statements | `epics` |
| Contains user story format (As a... I want... So that...), GWT acceptance criteria (Given... When... Then...) | `user-story` |
| Contains task breakdown, implementation steps, file-level expected changes, implementation checklists | `task` |
| Contains TC-NNN, test scenarios, test matrices, coverage mappings, test strategy | `test-plan` |
| Contains data model definitions, ERD, entity relationships, PlantUML entity diagrams, cardinality notations | `model` |
| Contains source code, import/using statements, function/class/method definitions, package declarations | `code` |
| `$ARGUMENTS` is a known artifact key (e.g., `spec`, `design`) — passed explicitly by the calling workflow | Classify directly from key name |
| Mixed or unclear signals | `other` |

**Disambiguation rules:**
- When multiple signals are present, prefer the dominant signal (the one with the most instances).
- When a document contains both FR-NNN and UC-NNN → classify as `spec` (use cases are part of spec, not a separate type).
- When a document contains both NFR-NNN and DR-NNN → classify as `design`.
- When content is pure prose with no structural IDs → classify as `other`.

## Upstream Inference

Based on the classified type, return the upstream artifact keys that the calling workflow should load for cross-referencing or context:

| Artifact Type | Upstream Keys (ordered by proximity) |
|---|---|
| `spec` | (none — spec is the root artifact) |
| `design` | `spec` |
| `epics` | `spec`, `design` |
| `user-story` | `epics`, `spec` |
| `task` | `spec`, `design` |
| `test-plan` | `spec`, `design` |
| `model` | `spec`, `design` |
| `code` | `design`, `spec` |
| `other` | (none) |

**Override:** When the calling workflow provides an explicit `--upstream` parameter, use those keys instead of the inferred set.

## Output

Return two values for the calling workflow to store:

1. `$ARTIFACT_TYPE` — one of: `spec` | `design` | `model` | `epics` | `user-story` | `task` | `test-plan` | `code` | `other`
2. `$UPSTREAM_KEYS` — ordered array of artifact keys (may be empty)

Log: `"Classified artifact as [type]. Upstream keys: [list or 'none']."`

## Error Handling

| Error | Message | Remediation |
|---|---|---|
| Input empty | "$ARGUMENTS is empty" | Halt; request calling workflow to resolve input first |
| No matching signals | "No classification signals found" | Classify as `other`; return no upstream keys |
| Ambiguous classification | "Multiple dominant signals: [types]" | Apply disambiguation rules; fall back to dominant-count |
