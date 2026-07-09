# Findings Registry — Schema

Structural contract for `.propel/learnings/findings-registry.md`. Writers (`/codify-finding` and any workflow that appends findings) resolve this schema via `/artifact-resolver findings_registry` and conform to it.

## File Structure

```markdown
<!-- Schema: ./findings-registry-schema.md -->
# Findings Registry

## Index

| File | Finding IDs |
|------|-------------|

## Entries

```yaml
- id: F<NNN>
  file: <path>
  cat: <category>
  type: <finding|decision>
  severity: <CRITICAL|HIGH>
  issue: <max 10 words>
  cause: <max 20 words>
  date: <YYYY-MM-DD>
  workflow: <canonical workflow name>
```
```

## Index Columns

| Column | Rule |
|--------|------|
| File | Repo-root-relative path. One row per file. Existing rows get new IDs appended. |
| Finding IDs | Comma-separated F-IDs in ascending order. |

## Entry Fields

| Field | Type | Rule |
|-------|------|------|
| `id` | string | `F<NNN>` zero-padded, globally sequential, never reused after archival. |
| `file` | string | Same value as Index column. Must match exactly. |
| `cat` | enum | `code-review` \| `challenge` \| `edge-case` \| `devops-security` \| `ux-review` \| `implementation-decision` \| `bug-triage`. |
| `type` | enum | `finding` (issue observed) \| `decision` (inferred coding/architecture choice logged for downstream awareness). |
| `severity` | enum | `CRITICAL` \| `HIGH`. MEDIUM/LOW are NOT codified. |
| `issue` | string | Reader-perspective summary, max 10 words, no trailing period. |
| `cause` | string | Root cause, max 20 words. Use `root-cause-unknown` if truly unknown. |
| `date` | string | `YYYY-MM-DD`. |
| `workflow` | string | Canonical workflow name (prompt filename without `.md`). |

## Archival

When live entry count reaches 40, `/codify-finding` rotates the oldest 10 to `findings-registry-archive-<YYYYMMDD>.md` and continues ID allocation from the highest live + archived ID. IDs are never reused.

## Example

```yaml
- id: F007
  file: src/api/users.ts
  cat: code-review
  type: finding
  severity: HIGH
  issue: SQL injection via unvalidated query parameter
  cause: Direct string concatenation; missing parameterized-query abstraction in data layer
  date: 2026-04-16
  workflow: review-code
```
