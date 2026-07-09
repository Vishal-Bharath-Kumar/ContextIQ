# Signal Ledger — Schema

Structural contract for `.propel/learnings/signal-ledger.md`. Writers (requirement-generating workflows' Inferred Requirement Review step) resolve this schema via `/artifact-resolver signal_ledger` and conform to it.

## File Structure

```markdown
<!-- Schema: ./signal-ledger-schema.md -->
# Signal Ledger

| Date | Workflow | Action | Requirement | Detail |
|------|----------|--------|-------------|--------|
```

Append-only. Rows added chronologically. Header and preamble are never rewritten.

## Columns

| Column | Type | Rule |
|--------|------|------|
| `Date` | string | `YYYY-MM-DD`. The date the review ran. |
| `Workflow` | string | Canonical workflow name (matches `--workflow-type`). |
| `Action` | enum | `REJECTED` \| `CORRECTED`. `ACCEPTED` and `SKIPPED` are NOT logged. |
| `Requirement` | string | `<ID> — <summary, max 12 words>`. ID matches the artifact's scheme (FR-###, UXR-###, etc.). |
| `Detail` | string | REJECTED: reason, max 25 words (or `no-reason-provided`). CORRECTED: `old: <value> → new: <value>`, max 40 words. |

## Example Rows

```markdown
| 2026-04-16 | spec | REJECTED | FR-012 — Session timeout after 30 minutes | user keeps rejecting session management inferences |
| 2026-04-16 | design | CORRECTED | NFR-007 — Response time <2s | old: <2s → new: <500ms p95 |
```
