"""Agent worker configuration — reads from environment variables.

``APP_ENV=development`` (or ``CONTEXTIQ_DEBUG=true``) activates debug mode,
which enables runtime contract enforcement in the ``@node_contract`` decorator.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Environment-driven configuration for the agent worker.

    Environment variables::

        CONTEXTIQ_DEBUG=true        # enable node contract enforcement
        APP_ENV=development         # alternative: sets debug=True when == "development"
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTEXTIQ_",
        env_file=".env",
        extra="ignore",
    )

    debug: bool = False
    app_env: str = "production"
    connector_timeout_seconds: float = 5.0

    def model_post_init(self, __context: object) -> None:
        if self.app_env.lower() == "development":
            object.__setattr__(self, "debug", True)


settings = AgentSettings()

# ── Intent confidence threshold (US-009 AC-5) ─────────────────────────────────
INTENT_CONFIDENCE_THRESHOLD: float = 0.6

# ── Clarification round cap (US-011 AC-6) ─────────────────────────────────────
MAX_CLARIFICATION_ROUNDS: int = 1  # cap at one round-trip; no inline literals elsewhere
