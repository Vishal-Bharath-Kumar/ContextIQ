<!-- Schema: ./findings-registry-schema.md -->
# Findings Registry

## Index

| File | Finding IDs |
|------|-------------|
| .github/prompts/contextiq.prompt.md | F001 |

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
```