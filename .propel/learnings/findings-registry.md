<!-- Schema: ./findings-registry-schema.md -->
# Findings Registry

## Index

| File | Finding IDs |
|------|-------------|
| .github/prompts/contextiq.prompt.md | F001 |
| frontend/admin-portal/src/routes/index.tsx | F002 |

## Entries

```yaml
- id: F001
  file: .github/prompts/contextiq.prompt.md
  cat: implementation-decision
  type: decision
  severity: HIGH
  issue: Always invoke generate_context first
  cause: Prompt left context generation conditional for slash command execution
  date: 2026-08-04
  workflow: contextiq.prompt
- id: F002
  file: frontend/admin-portal/src/routes/index.tsx
  cat: bug-triage
  type: finding
  severity: HIGH
  issue: Old add-model route still shipped
  cause: models/add stayed registered and compose served stale dist bundle via nginx
  date: 2026-08-12
  workflow: copilot-chat
```