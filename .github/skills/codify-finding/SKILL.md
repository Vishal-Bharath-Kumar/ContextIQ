---
name: codify-finding
description: Append CRITICAL and HIGH severity findings to the findings registry. Handles path resolution, archival rotation, YAML entry formatting, and index updates. Called by workflow steps only — not directly user-invocable. WHEN: workflow references /codify-finding, persist step needs findings codification, review workflow produces severity-classified findings.
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

## Input

- `$FINDINGS` — CRITICAL and HIGH entries only. Each must carry the fields required by the findings-registry schema (`file`, `cat`, `type`, `severity`, `issue`, `cause`, `workflow`). See schema for enum values and length limits.
- `$REFERENCE_DOCS[findings_registry]` — resolved registry path from the calling workflow's Step 0.

## Codification Logic

### Step 1 — Resolve schema and registry

1. Call `/artifact-resolver findings_registry` → obtain `propelFilePath` and `schema`.
2. Read the schema file. If unreadable → halt and report. The schema is the authority on entry format, enums, ID sequencing, and archival rules — do NOT guess or restate them.
3. If the registry file does not exist → create it from the structure defined in the schema (including the `<!-- Schema: -->` header).

### Step 2 — Archival, ID allocation, append

Follow the schema's rules for:
- Archival threshold and rotation (when to roll entries into `findings-registry-archive-<YYYYMMDD>.md`).
- Next F-ID allocation (global sequence, non-reusable).
- YAML entry shape and field constraints.

Append today's date (`YYYY-MM-DD`) as the `date` field. Use the calling prompt's filename (without `.md`) as the `workflow` field.

### Step 3 — Update index

Update the `## Index` table: append new F-IDs to the existing row for each file, or add a new row for files not yet indexed.

## Output

- Per finding: `"Codified [finding_id] → F[seq] in findings registry (cat: [category])."`
- Final: `"Codified [N] findings to findings registry. Registry now has [total] entries."`
- On archival: `"Archived [10] oldest entries to [archive file path]."`

## Error Handling

| Error | Message | Remediation |
|---|---|---|
| Schema unreadable | "Cannot read findings-registry schema" | Halt and report the schema path |
| Missing required field | "$FINDINGS[i] missing field [name]" | Halt; ask calling workflow to fix finding entry |
| Registry write failure | "Cannot write to registry at [path]" | Halt; surface filesystem error |
| Archival threshold exceeded | (schema-defined) | Rotate per schema rules; log archive target |
