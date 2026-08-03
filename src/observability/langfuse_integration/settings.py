"""Langfuse configuration settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class LangfuseSettings(BaseSettings):
    """
    Langfuse observability settings.
    
    Following Langfuse best practices:
    - PUBLIC_KEY and SECRET_KEY for authentication
    - BASE_URL for cloud or self-hosted deployment
    - ENABLED flag to disable in development
    """
    model_config = SettingsConfigDict(
        env_prefix="LANGFUSE_",
        env_file=".env",
        extra="ignore",
    )

    public_key: str = ""
    secret_key: str = ""
    base_url: str = "https://cloud.langfuse.com"
    enabled: bool = True
    
    # Flush settings
    flush_interval: int = 1  # seconds
    
    # Environment metadata
    environment: str = "development"
    release: str = "0.1.0"

    @property
    def is_configured(self) -> bool:
        """Check if Langfuse is properly configured."""
        return bool(self.public_key and self.secret_key and self.enabled)
