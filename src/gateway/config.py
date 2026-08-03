"""
Gateway configuration — reads from environment variables with CONTEXTIQ_ prefix.

TASK-US001-01: Configure FastMCP Server with SSE and WebSocket Transport.
TASK-US001-05: OTel endpoint and sampler settings.TASK-US003-02: Agent Worker HTTP Client and Output Schema Validation."""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """
    Environment-driven configuration for the MCP Gateway.

    Required environment variables::

        CONTEXTIQ_MCP_PATH=/mcp
        CONTEXTIQ_SERVER_VERSION=0.1.0
        CONTEXTIQ_LOG_LEVEL=INFO
        OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger-collector:4317
        OTEL_TRACES_SAMPLER_ARG=1.0
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTEXTIQ_",
        env_file=".env",
        extra="ignore",
    )

    mcp_path: str = "/mcp"
    server_version: str = "0.1.0"
    log_level: str = "INFO"

    # Agent Worker settings — TASK-US003-02
    agent_worker_base_url: str = (
        "http://contextiq-agent-worker.contextiq-agents.svc.cluster.local"
    )
    agent_worker_timeout_seconds: float = 5.0

    # Vault settings — TASK-US003-02 (EP-TECH-002)
    vault_addr: str = "http://vault.vault.svc.cluster.local:8200"
    vault_role: str = "contextiq-gateway"

    # Keycloak client settings — TASK-US004-03
    # Used to extract per-client roles from resource_access.<client-id>.roles
    keycloak_client_id: str = "contextiq-gateway"

    # OTel settings — no CONTEXTIQ_ prefix; read from standard OTel env vars.
    otel_endpoint: str = "http://jaeger-collector:4317"
    otel_sampler_arg: float = 1.0

    @field_validator("server_version", mode="before")
    @classmethod
    def _normalise_local_version(cls, value: object) -> object:
        if isinstance(value, str) and value.endswith("-local"):
            return value.removesuffix("-local")
        return value

    model_config = SettingsConfigDict(
        env_prefix="CONTEXTIQ_",
        env_file=".env",
        extra="ignore",
        # Allow non-prefixed OTel env vars to be read directly.
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(  # type: ignore[override]
        cls,
        settings_cls: type[BaseSettings],
        **kwargs: object,
    ) -> tuple[object, ...]:
        from pydantic_settings import EnvSettingsSource, InitSettingsSource

        return (
            InitSettingsSource(settings_cls, init_kwargs={}),
            _OtelEnvSource(settings_cls),
            EnvSettingsSource(settings_cls),
        )


class _OtelEnvSource:
    """Map bare OTel env-var names to GatewaySettings fields."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        self._cls = settings_cls

    def __call__(self) -> dict[str, object]:
        import os

        result: dict[str, object] = {}
        if val := os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            result["otel_endpoint"] = val
        if val := os.environ.get("OTEL_TRACES_SAMPLER_ARG"):
            result["otel_sampler_arg"] = float(val)
        return result


settings = GatewaySettings()
