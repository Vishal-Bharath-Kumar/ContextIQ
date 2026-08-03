"""Pydantic schemas for OPA authorization input/output contracts.

These schemas form the data contract between the governance pipeline,
the OPA sidecar, and the execution trace.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChunkAuthzInput(BaseModel):
    """Input document sent to OPA for each context chunk.

    Shape matches the Rego rule input:
      data.contextiq.authz.allow with input as ChunkAuthzInput.model_dump()
    """

    model_config = ConfigDict(frozen=True)

    # User context
    user_roles: list[str] = Field(
        description="Roles extracted from the Keycloak JWT (e.g. ['developer', 'read-only']).",
        min_length=0,
    )
    tenant_id: str = Field(min_length=1, max_length=128)

    # Chunk provenance
    source_id: str = Field(
        description="UUID of the knowledge source as a string.",
    )
    chunk_id: str
    document_id: str = Field(default="")

    # Classification label assigned by the connector or source policy (AC-2).
    # Defaults to 'internal' if the connector does not assign a label.
    classification_label: str = Field(
        default="internal",
        description=(
            "Data classification of the document. "
            "Typical values: 'public', 'internal', 'confidential', 'restricted'."
        ),
    )


class PolicyDecision(BaseModel):
    """Structured response from OPA `data.contextiq.authz.allow` evaluation."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    # True = chunk is allowed through; False = chunk is denied and filtered.
    allow: bool
    # Human-readable reason string from the Rego `deny_reason` rule, if any.
    # Empty string when allow=True.
    rationale: str = Field(default="")
    # Wall-clock evaluation time in milliseconds for this single chunk.
    eval_ms: float = Field(ge=0.0)

    @property
    def is_denied(self) -> bool:
        return not self.allow


class AuthzFilterResult(BaseModel):
    """Output of a full OPA filter pass over all context chunks.

    Consumed by opa_filter_node() to update ranked_context and execution_trace.
    """

    model_config = ConfigDict(frozen=True)

    decisions: list[PolicyDecision]
    allowed_chunk_ids: list[str]
    denied_chunk_ids: list[str]
    total_eval_ms: float
    bundle_version: str = Field(
        description="Version tag of the active OPA bundle at the time of evaluation.",
        default="unknown",
    )

    @property
    def denial_count(self) -> int:
        return len(self.denied_chunk_ids)


class BundleInfo(BaseModel):
    """Metadata about the currently loaded OPA policy bundle."""

    model_config = ConfigDict(frozen=True)

    version: str
    loaded_at: datetime
    source_url: str = Field(description="URL or path from which the bundle was fetched.")
