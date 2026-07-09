---
name: artifact-resolver
description: Resolve project artifact metadata (file path, content type, MCP type, templates) from project-config.json. WHEN: "show me the spec", "where is the design doc", "list artifacts", "resolve artifact path", "read the [artifact-name]".
license: MIT
metadata:
  author: KANINI
  version: 1.0.0
---

# Project Artifact Resolver

This skill reads the bundled `assets/project-config.json` and resolves artifact metadata so you know exactly where to find project documents and how to work with them.

## Slash command usage

This skill can be invoked explicitly as `/artifact-resolver <arg>`:

- `/artifact-resolver <key>` — resolve any named artifact (e.g., `spec`, `design`, `model`)
- `/artifact-resolver --list` — list all available artifact keys
- `/artifact-resolver --all` — resolve all artifacts at once

`<key>` is any artifact key defined in `assets/project-config.json`. Use `--list` first if unsure what keys exist.

When invoked via slash command, parse the argument and run the resolver script accordingly.
`<skill-path>` is the absolute path to the directory containing this SKILL.md file — resolve it at runtime before executing any script:

```bash
# If arg is --list
python <skill-path>/scripts/resolve_artifact.py --list

# If arg is --all
python <skill-path>/scripts/resolve_artifact.py --all

# Otherwise, treat arg as an artifact key
python <skill-path>/scripts/resolve_artifact.py --artifact <key>
```

Present the JSON output to the user in a readable format.

## When to use (auto-trigger)

- A user asks to read, update, or reference a project artifact by name (e.g., "show me the spec", "update the design doc")
- You need to discover what artifacts exist in the project
- You need to know the file path, template path, content type, or MCP type of an artifact before operating on it
- Another skill or workflow declares this skill as a dependency and calls it in an early resolution step
- Any workflow step needs to resolve an artifact path before reading, writing, or loading a file

## How it works

The project configuration is bundled at `assets/project-config.json` within the skill folder. It has this structure:

```json
{
  "projectName": "Project Name",
  "description": "Project Description",
  "basePropelPath": "./.propel/context",
  "baseProjectPath": "./",
  "artifacts": {
    "<artifact-key>": {
      "propelFileName": "spec.md",
      "propelDirPath": "${basePropelPath}/docs",
      "projectFileName": "spec.pdf",
      "projectDirPath": "${baseProjectPath}/docs/",
      "templates": {
        "default": ".propel/templates/requirements-template.md"
      },
      "contentType": "pdf",
      "mcpType": "local",
      "references": []
    }
  }
}
```

Each artifact entry provides:
- **propelFileName** — filename of the propel markdown source
- **propelDirPath** — directory path for the propel markdown source (supports `${var}` interpolation)
- **templates** — object map of named template paths used by this artifact's workflow. Keys are template names (e.g., `"default"` for single-template workflows, or named keys like `"information_architecture"` for multi-template workflows). Values are fixed paths relative to project root (not interpolated). Empty object `{}` if no templates.
- **schema** — *(optional)* path to a schema file that defines the structure of the artifact itself (not its template). Used for append-only registries like `signal_ledger` and `findings_registry` whose format is enforced by a schema document. Workflows writing to the artifact MUST read the schema before formatting entries. Empty string `""` if the artifact has no schema contract.
- **projectFileName** — filename of the project deliverable (e.g. PDF, DOCX)
- **projectDirPath** — directory path for the project deliverable (supports `${var}` interpolation)
- **contentType** — format of the project deliverable (e.g. `pdf`, `docx`)
- **mcpType** — how the artifact is accessed (`local` for files on disk, or other MCP transport types)
- **references** — array of artifact keys this artifact may consult on demand as context (non-blocking — unavailable references are skipped). For `change_request`, the array order also defines the execution sequence used by `/apply-change`.
- **workflow** — *(optional)* slash command that creates or updates this artifact (e.g., `/create-spec`). Empty string `""` if the artifact has no creator workflow (e.g., `findings_registry`, `signal_ledger`). Used by `/request-change` and `/apply-change` to map CR rows to the workflow that processes them.

## Resolved output schema

When you call `/artifact-resolver <key>`, the resolver returns:

```json
{
  "artifact": "spec",
  "propelFileName": "spec.md",
  "propelFileNames": {},
  "propelDirPath": "./.propel/context/docs",
  "propelFilePath": "./.propel/context/docs/spec.md",
  "projectFilePath": "./docs/spec.pdf",
  "propelUmlPath": "./.propel/context/docs/uml-models",
  "projectUmlPath": "./docs/uml-models",
  "templates": {
    "default": ".propel/templates/requirements-template.md"
  },
  "schema": "",
  "contentType": "pdf",
  "mcpType": "local",
  "references": [],
  "workflow": "/create-spec"
}
```

- **propelFileName** — filename of the propel markdown source, passed through from config as-is. May contain documentation tokens like `<seq>`, `<name>`, `<timestamp>` which the consuming workflow substitutes at write time.
- **propelFileNames** — map of named filenames (keyed by template name) for multi-file artifacts (e.g., `wireframe`, `automation_test`, `playwright_scripts`). Empty `{}` for single-file artifacts. Tokens substituted by the consuming workflow.
- **propelDirPath** — fully resolved directory path for the propel output (interpolation applied)
- **propelFilePath** — fully resolved path to the propel markdown source (= `propelDirPath` + `propelFileName`). For multi-file artifacts where `propelFileName` is empty, this path ends with `/` and callers should compose per-file paths from `propelDirPath` + entries in `propelFileNames`.
- **projectFilePath** — fully resolved path to the project deliverable
- **propelUmlPath** — fully resolved path for UML diagram files (`.puml`, `.mmd`, `.png`) co-located with the propel output. Derived by appending the fixed `uml-models` subdirectory to `propelDirPath`.
- **projectUmlPath** — fully resolved path for UML diagram files co-located with the project deliverable. Derived by appending the fixed `uml-models` subdirectory to `projectDirPath`.
- **templates** — object map of named template paths, passed through from config as-is
- **schema** — path to the artifact's schema contract, passed through from config as-is (empty string if the artifact has no schema)
- **contentType** / **mcpType** / **references** / **workflow** — passed through from config as-is

## Resolving artifacts

### Option 1: Use the resolver script

Run the bundled script for quick lookups:

```bash
# List all artifacts
python <skill-path>/scripts/resolve_artifact.py --list

# Resolve a specific artifact
python <skill-path>/scripts/resolve_artifact.py --artifact spec

# Resolve all artifacts as JSON
python <skill-path>/scripts/resolve_artifact.py --all
```

The script outputs JSON, making it easy to parse programmatically.

### Option 2: Read the config directly

For simple cases, just read the bundled `<skill-path>/assets/project-config.json` and extract the artifact entry you need. The structure is flat and predictable — no script needed for a single lookup.

## After resolving

Once you have the artifact details, act on `mcpType` first, then interpret content using `contentType`:

**mcpType handling:**
- `local` — read the file directly using the resolved `propelFilePath`. Prepend the project root if the path is relative.
- Any other value — use the MCP tool or transport matching that type. If no matching tool is available, report the unresolved transport and stop; do not attempt to guess or substitute.

**contentType handling:**
- `markdown` — read as plain text; render or parse as Markdown.
- `json` — parse as structured JSON data.
- `yaml` — parse as structured YAML data.
- Any other value — read as plain text and treat the value as a hint about structure. If the content cannot be interpreted, report the content type and surface the raw content for the caller to handle.

## Error handling

- If `assets/project-config.json` doesn't exist, inform the user that the project hasn't been configured yet
- If the requested artifact key doesn't exist, list the available artifacts so the user can pick the right one
- If a `${variable}` reference in the config cannot be resolved, the script exits with a JSON error identifying the unresolved variable
- If the resolved `mcpType` is not supported by any available tool, report an error indicating the unsupported transport type
- If the resolved `contentType` is not recognized, return the raw content with a warning about the unknown content type, so the caller can decide how to proceed