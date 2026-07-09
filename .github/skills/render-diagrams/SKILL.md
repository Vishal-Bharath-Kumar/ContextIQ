---
name: render-diagrams
description: Render PlantUML (.puml) and Mermaid (.mmd) source files to PNG (default) or SVG. OS-dispatched — picks the right renderer script for the host platform. Use when: "render diagrams", "convert puml to png", "convert mmd to png", "produce diagram images", "render sidecars", "render as svg". DO NOT USE FOR: authoring new diagrams — use /plantuml or /mermaid-diagrams.
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

# Diagram Renderer (OS-dispatched)

Renders a caller-supplied list of diagram sources to image files. Handles platform dispatch, dependency pre-flight, and per-file invocation.

## Slash command

```
/render-diagrams [--format png|svg] <source-1> [<source-2> ...]
```

- `--format` — `png` (default) or `svg`. Applies to every source in the invocation.
- `<source-N>` — absolute path to a `.puml` or `.mmd` file.

Output is written next to each source, same basename, only the extension changes (`foo.puml` → `foo.png` or `foo.svg`). Pass only the files produced by the current run — never sweep `$UML_SOURCE_DIR`, as that re-renders stale sidecars.

## Execution

1. **Resolve script by host OS:**

   | Host | Script |
   |------|--------|
   | `win32` + PowerShell | `<skill-path>/scripts/diagram.ps1` |
   | `win32` + `cmd.exe` / legacy CI | `<skill-path>/scripts/diagram.cmd` |
   | `darwin` / `linux` | `<skill-path>/scripts/diagram.sh` |
   | other | return `FAILED` with `UNSUPPORTED_OS` |

   Full CLI reference: [references/diagram-cli.md](references/diagram-cli.md).

2. **Pre-flight** — run `<script> --check` once. If Java, `plantuml.jar`, or `mmdc` is missing: record every source as `SKIPPED` with the dep error, return verdict `OK`, do not render.

3. **Render** — one subprocess per source:
   - PNG: `<script> <source>`
   - SVG: `<script> <source> --svg`

## Output contract

1. **render_log** — markdown table, one row per source:

   | Source | Target | Status | Error |
   |--------|--------|--------|-------|
   | `<abs-path>.puml` | `<abs-path>.png` \| `.svg` | RENDERED \| SKIPPED \| FAILED | stderr on failure |

2. **verdict** — `OK` if every row is RENDERED or SKIPPED; `FAILED` if any row is FAILED.

Callers treat `FAILED` as blocking and `SKIPPED` as non-blocking — their own quality gate surfaces missing images.