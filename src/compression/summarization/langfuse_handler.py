"""Langfuse callback factory for LLM-based chunk summarisation (TASK-US017-05 / EP-005)."""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.compression.summarization.settings import get_summarization_settings
from src.observability.cost.settings import LangfuseProjectSettings


class _RequiredLangfuseCredentials(BaseSettings):
    """Validates that Langfuse credentials are present.

    Raises ``pydantic.ValidationError`` at instantiation time when
    ``LANGFUSE_PUBLIC_KEY`` is empty or unset.  Used by
    :func:`make_langfuse_handler` to surface missing-credential errors at
    application startup rather than silently at the first LLM summarisation.
    """

    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_",
        env_file=".env",
        extra="ignore",
    )

    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"

    @model_validator(mode="after")
    def _require_public_key(self) -> _RequiredLangfuseCredentials:
        if not self.public_key:
            raise ValueError(
                "LANGFUSE_PUBLIC_KEY must be set when SUMMARIZATION_LANGFUSE_ENABLED=true"
            )
        return self


# Module-level singleton — populated lazily on first call to make_langfuse_handler
# when langfuse_enabled=True.  Kept as None until then so the module can be safely
# imported in test environments without requiring real Langfuse credentials.
_langfuse_settings: LangfuseProjectSettings | None = None


def make_langfuse_handler(
    request_id: str,
    user_id: str,
    session_id: str,
) -> object | None:
    """Return a configured Langfuse ``CallbackHandler``, or ``None`` if disabled.

    Credentials are validated on the first call when tracing is enabled.
    Raises ``pydantic.ValidationError`` if ``LANGFUSE_PUBLIC_KEY`` is unset,
    surfacing mis-configuration before the first LLM summarisation call.

    Args:
        request_id: UUID string for the current pipeline request.
        user_id: JWT ``sub`` claim identifying the calling user.
        session_id: Langfuse session identifier; typically equal to
            ``request_id`` so all summarisation spans group under one trace.

    Returns:
        A :class:`langfuse.callback.CallbackHandler` when tracing is
        enabled, or ``None`` when ``SUMMARIZATION_LANGFUSE_ENABLED=false``.
    """
    global _langfuse_settings

    if not get_summarization_settings().langfuse_enabled:
        return None

    if _langfuse_settings is None:
        # Validates LANGFUSE_PUBLIC_KEY is set; raises ValidationError if missing.
        _RequiredLangfuseCredentials()
        _langfuse_settings = LangfuseProjectSettings()

    # Import deferred to avoid hard dependency when Langfuse is disabled.
    from langfuse.callback import CallbackHandler  # noqa: PLC0415

    return CallbackHandler(
        public_key=_langfuse_settings.public_key,
        secret_key=_langfuse_settings.secret_key,
        host=_langfuse_settings.host,
        trace_name="context_summarization",
        metadata={
            "request_id": request_id,
            "user_id": user_id,
            "session_id": session_id,
        },
        tags=["compression", "summarization"],
    )

