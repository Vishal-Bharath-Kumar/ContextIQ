# ID Scheme Registry

Canonical ID patterns used across PropelIQ templates and prompts. Templates reference this registry; prompts never invent new schemes.

## Universal Conventions

- **Separator**: hyphen (`-`). Never underscore.
- **Padding**: three digits, zero-padded, unless stated otherwise (e.g., `FR-001`, not `FR-1`).
- **Ranges are closed sets where specified** — out-of-range allocation is a schema violation, not an extension point.
- **IDs are stable**: once assigned, an ID never changes meaning. Renaming requires a new ID and archival of the old.

## Requirement Schemes

| Scheme | Range | Owner Template | Meaning |
|--------|-------|----------------|---------|
| `FR-###` | 001–999 | requirements-template.md | Functional requirement |
| `NFR-###` | 001–999 | design-specification-template.md | Non-functional requirement |
| `TR-###` | 001–999 | design-specification-template.md | Technical requirement |
| `DR-###` | 001–999 | design-specification-template.md | Data requirement |
| `AIR-###` | 001–999 | design-specification-template.md | AI requirement |
| `UXR-###` | see below | figma-specification-template.md | UX requirement (multi-range) |
| `UC-###` | 001–999 | requirements-template.md | Use case |

### UXR sub-ranges (closed set)

| Range | Category |
|-------|----------|
| `UXR-001`–`UXR-099` | Project-wide / cross-cutting |
| `UXR-1##` | Usability |
| `UXR-2##` | Accessibility |
| `UXR-3##` | Interaction / motion |
| `UXR-4##` | Visual / aesthetic |

## Test Scheme

| Scheme | Range | Owner Template | Meaning |
|--------|-------|----------------|---------|
| `TC-###` | 001–999 | test-plan-template.md | Test case (base form) |
| `TC-<TYPE>-###` | compound | test-plan-template.md | Test case derived from a requirement type — see compound rule below |
| `E2E-<JOURNEY>` | compound | test-plan-template.md | End-to-end journey test |
| `EC-###` | 001–999 | unit-test-template.md | Edge case test |
| `ES-###` | 001–999 | unit-test-template.md | Error scenario test |

### Compound `TC-<TYPE>-###` rule

When a test case maps to a specific requirement type, the compound form is mandatory:

- `TC-FR-<FR-ID>-<seq>` — test case for FR-NNN (e.g., `TC-FR-001-001`).
- `TC-NFR-<NFR-ID>-<seq>` — test case for NFR-NNN.
- `TC-AIR-<AIR-ID>-<seq>` — test case for AIR-NNN.
- `TC-DR-<DR-ID>-<seq>` — test case for DR-NNN.
- `TC-TR-<TR-ID>-<seq>` — test case for TR-NNN.

The trailing `<seq>` is a 3-digit sequence within the compound key (starts at 001 per compound prefix).

## Grouping and Planning Schemes

| Scheme | Range | Owner Template | Meaning |
|--------|-------|----------------|---------|
| `EP-###` | 001–999 | epics-template.md | Epic |
| `EP-TECH-###` | 001–099 | epics-template.md | Auto-generated technical epic (`[SOURCE:INFERRED]`) |
| `EP-DATA-###` | 001–099 | epics-template.md | Auto-generated data epic (`[SOURCE:INFERRED]`) |
| `US-###` | 001–999 | user-story-template.md | User story. **Migration from `US_###`** — hyphen form is canonical; templates using underscore are to be updated in Phase 3. |
| `TASK-###` | 001–999 | task-template.md | Task |
| `BUG-###` | 001–999 | issue-triage-template.md | Bug triage entry |

## Project and Sprint Schemes

| Scheme | Range | Owner Template | Meaning |
|--------|-------|----------------|---------|
| `GOAL-###` | 001–099 | project-plan-template.md, design-specification-template.md | Architecture or project goal. **New scheme** — replaces plain bullets currently used. |
| `OBJ-###` | 001–099 | project-plan-template.md | Business objective |
| `MS-###` | 001–099 | project-plan-template.md | Milestone |
| `RK-###` | 001–099 | project-plan-template.md | Risk |
| `SP-###` | 001–099 | sprint-plan-template.md | Sprint |
| `SG-###` | 001–099 | sprint-plan-template.md | Sprint goal. **New formal scheme** — was inline text; templates to be updated in Phase 3. |
| `SPR-###` | 001–099 | sprint-plan-template.md | Sprint risk (project-plan-wide risks stay `RK-###`) |
| `REC-###` | 001–099 | sprint-plan-template.md | Recommendation |

## Registry and Operational Schemes

| Scheme | Range | Owner | Meaning |
|--------|-------|-------|---------|
| `F###` | 001–999 | findings-registry-schema.md | Finding (note: no hyphen — schema is authoritative). Global sequence; non-reusable after archival. |

## Modernisation and Infrastructure Schemes

| Scheme | Range | Owner Template | Meaning |
|--------|-------|----------------|---------|
| `MOD-###` | 001–999 | (modernization-plan template, future) | Modernisation requirement |
| `INFRA-###` | 001–999 | (infra-spec template, future) | Infrastructure requirement |
| `SEC-###` | 001–999 | (infra-spec template, future) | Security requirement |
| `OPS-###` | 001–999 | (infra-spec template, future) | Operations requirement |
| `ENV-###` | 001–099 | (infra-spec template, future) | Environment configuration |
| `CICD-0##` | 001–099 | (cicd-spec template, future) | CI/CD requirement |

## Adding a New Scheme

1. Propose a prefix unique across this registry.
2. Declare the range, owner template, and meaning.
3. Add a row to this table.
4. Reference this row from the owning template — do not redefine the scheme in the template.

Schemes are append-only. Removing a scheme requires explicit archival guidance for existing artifacts using it.
