# TASK-US032-01 — OPA Schemas: `ChunkAuthzInput`, `PolicyDecision`, `AuthzFilterResult`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US032-01 |
| User Story | US-032 |
| Epic | EP-010 — Governance Engine & Policy Enforcement |
| Layer | Backend / Data |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Define the Pydantic schemas that form the data contract between the governance pipeline, the OPA sidecar, and the execution trace: `ChunkAuthzInput` (the JSON payload sent to OPA per chunk), `PolicyDecision` (the structured OPA response), and `AuthzFilterResult` (the full filter pass output). Also defines `BundleInfo` for bundle version tracking and the `AgentState` fields introduced by US-032. These schemas are consumed by `OPAClient` (TASK-US032-02) and `opa_filter_node()` (TASK-US032-04).

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2

**File locations:**
- `src/governance/opa/schemas.py` — `ChunkAuthzInput`, `PolicyDecision`, `AuthzFilterResult`, `BundleInfo`
- `src/agents/state.py` — extend existing `AgentState` TypedDict
- `tests/governance/test_opa_schemas.py`

---

### `ChunkAuthzInput`

The OPA input document sent for each chunk. Maps to the Rego `input` object evaluated against `data.contextiq.authz.allow`.

```python
# src/governance/opa/schemas.py
from __future__ import annotations
from uuid    import UUID
from pydantic import BaseModel, ConfigDict, Field


class ChunkAuthzInput(BaseModel):
    """
    Input document sent to OPA for each context chunk.
    Shape matches the Rego rule input:
      data.contextiq.authz.allow with input as ChunkAuthzInput.model_dump()
    """
    model_config = ConfigDict(frozen=True)

    # User context
    user_roles:           list[str] = Field(
        description="Roles extracted from the Keycloak JWT (e.g. ['developer', 'read-only']).",
        min_length=0,
    )
    tenant_id:            str = Field(min_length=1, max_length=128)

    # Chunk provenance
    source_id:            str = Field(
        description="UUID of the knowledge source as a string.",
    )
    chunk_id:             str
    document_id:          str = Field(default="")

    # Classification label assigned by the connector or source policy (AC-2).
    # Defaults to 'internal' if the connector does not assign a label.
    classification_label: str = Field(
        default="internal",
        description=(
            "Data classification of the document. "
            "Typical values: 'public', 'internal', 'confidential', 'restricted'."
        ),
    )
```

---

### `PolicyDecision`

```python
# src/governance/opa/schemas.py (continued)

class PolicyDecision(BaseModel):
    """Structured response from OPA `data.contextiq.authz.allow` evaluation."""
    model_config = ConfigDict(frozen=True)

    chunk_id:   str
    # True = chunk is allowed through; False = chunk is denied and filtered.
    allow:      bool
    # Human-readable reason string from the Rego `deny_reason` rule, if any.
    # Empty string when allow=True.
    rationale:  str = Field(default="")
    # Wall-clock evaluation time in milliseconds for this single chunk.
    eval_ms:    float = Field(ge=0.0)

    @property
    def is_denied(self) -> bool:
        return not self.allow
```

---

### `AuthzFilterResult`

```python
# src/governance/opa/schemas.py (continued)

class AuthzFilterResult(BaseModel):
    """
    Output of a full OPA filter pass over all context chunks.
    Consumed by opa_filter_node() to update ranked_context and execution_trace.
    """
    model_config = ConfigDict(frozen=True)

    decisions:          list[PolicyDecision]
    allowed_chunk_ids:  list[str]
    denied_chunk_ids:   list[str]
    total_eval_ms:      float
    bundle_version:     str = Field(
        description="Version tag of the active OPA bundle at the time of evaluation.",
        default="unknown",
    )

    @property
    def denial_count(self) -> int:
        return len(self.denied_chunk_ids)
```

---

### `BundleInfo`

```python
# src/governance/opa/schemas.py (continued)
from datetime import datetime

class BundleInfo(BaseModel):
    """Metadata about the currently loaded OPA policy bundle."""
    model_config = ConfigDict(frozen=True)

    version:    str
    loaded_at:  datetime
    source_url: str = Field(description="URL or path from which the bundle was fetched.")
```

---

### `AgentState` extensions (US-032 additions)

```python
# src/agents/state.py  — extend existing TypedDict (do NOT replace)
from typing import NotRequired
from src.governance.opa.schemas import PolicyDecision

class AgentState(TypedDict):
    # … existing fields from US-031 and prior epics …

    # New fields added by opa_filter_node:
    opa_decisions:        NotRequired[list[PolicyDecision]]
    opa_denied_count:     NotRequired[int]
    opa_bundle_version:   NotRequired[str]
```

---

### Reference Rego policy

The canonical `data.contextiq.authz.allow` policy is bundled in the versioned policy repository. This snippet is the reference implementation that the OPA sidecar loads at startup (AC-1).

```rego
# policies/contextiq/authz/allow.rego
package contextiq.authz

import future.keywords.if
import future.keywords.in

# Default: deny unless explicitly allowed.
default allow = false

# Allow if user has at least one role that grants access to this classification.
allow if {
    some role in input.user_roles
    _role_grants_access(role, input.classification_label)
}

# Public content is accessible to all authenticated users.
_role_grants_access(_, "public") := true

# Internal content requires the base developer or reader role.
_role_grants_access("developer",  "internal") := true
_role_grants_access("read-only",  "internal") := true
_role_grants_access("admin",      "internal") := true

# Confidential content requires elevated roles.
_role_grants_access("senior-engineer", "confidential") := true
_role_grants_access("admin",           "confidential") := true

# Restricted content is admin-only.
_role_grants_access("admin", "restricted") := true

# Provide a human-readable reason when access is denied.
deny_reason := reason if {
    not allow
    reason := sprintf(
        "User roles %v lack access to classification '%v' for source '%v'",
        [input.user_roles, input.classification_label, input.source_id],
    )
}
```

**`classification_label` propagation:**

Connector sync jobs (US-026) store the `classification_label` in `KnowledgeSourceRecord` (e.g. via an optional `classification_label` column added to `knowledge_sources`). The `ChunkIndexedEvent` includes this label, which is stored in `ChunkPayload.metadata["classification_label"]`. The `governance_node`/`opa_filter_node` reads it from each context item's `metadata` dict, defaulting to `"internal"` if absent.

## Acceptance Criteria

- [ ] `ChunkAuthzInput` with `classification_label` not provided defaults to `"internal"`
- [ ] `PolicyDecision.is_denied` returns `True` when `allow=False`
- [ ] `AuthzFilterResult.denial_count` equals `len(denied_chunk_ids)`
- [ ] All four schema classes are frozen (`ConfigDict(frozen=True)`)
- [ ] `mypy --strict` passes

## Dependencies

- TASK-US031-04 (`AgentState` TypedDict — extended here)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] `mypy --strict` passes; no `ruff` lint errors
