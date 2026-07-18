"""RoutingSettings — environment-variable overrides for per-intent routing weights.

Each field accepts a JSON-encoded ``RoutingWeights`` object.  If set, the
override replaces the corresponding entry in ``INTENT_ROUTING_WEIGHT_TABLE``
at startup.  The table is built once at module import and treated as
immutable thereafter.

Environment variable names follow the ``ROUTING_WEIGHTS_<INTENT>`` pattern,
e.g. ``ROUTING_WEIGHTS_CODE_GENERATION``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class RoutingSettings(BaseSettings):
    """Pydantic-settings model for routing weight overrides."""

    model_config = SettingsConfigDict(env_prefix="ROUTING_", env_file=".env", extra="ignore")

    # Fallback and observability settings (TASK-US019-04)
    fallback_model_id: str = "gpt-4o-mini"
    langfuse_enabled: bool = True

    # Per-intent weight overrides (JSON-encoded RoutingWeights)
    weights_code_generation: str | None = None
    weights_summarization: str | None = None
    weights_code_review: str | None = None
    weights_documentation: str | None = None
    weights_question_answering: str | None = None
    weights_debugging: str | None = None
    weights_refactoring: str | None = None
    weights_general: str | None = None
