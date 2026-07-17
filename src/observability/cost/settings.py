from pydantic_settings import BaseSettings, SettingsConfigDict


class LangfuseProjectSettings(BaseSettings):
    """
    Langfuse project-level configuration.
    Retention (AC-5) is set at project creation time in the Langfuse admin UI
    or via the management API — not via the Python SDK.
    This settings object documents the required configuration for operators.
    """

    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_",
        env_file=".env",
        extra="ignore",
    )

    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"

    # AC-5: Langfuse project data retention must be set to >= 12 months
    # in the Langfuse project settings (Settings → Data Retention).
    # This constant is used in the startup health check to warn if unset.
    required_retention_months: int = 12
