from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MetricsSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="METRICS_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "contextiq-api"  # overridden per-service via METRICS_SERVICE_NAME
    enabled: bool = True
