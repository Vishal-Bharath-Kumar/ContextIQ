from pydantic_settings import BaseSettings, SettingsConfigDict

from src.model_registry.schemas.model_definition import LatencyTier


class InvokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVOKER_", env_file=".env", extra="ignore")

    timeout_fast_s: float = 10.0    # LatencyTier.FAST — p95 < 500 ms; allow 10 s for safety
    timeout_medium_s: float = 30.0  # LatencyTier.MEDIUM — p95 < 2 s; allow 30 s
    timeout_slow_s: float = 120.0   # LatencyTier.SLOW — o1-class; allow 120 s
    max_fallback_attempts: int = 3   # US-020 AC-3: max 3 fallbacks after primary
    fallback_chain_size: int = 4     # top-N models to pre-select (primary + 3 fallbacks)

    # Circuit breaker settings (TASK-US020-03 / US-020 AC-5)
    circuit_failure_threshold: int = 5   # failures within window before OPEN
    circuit_window_s: int = 60           # sliding window duration (seconds)
    circuit_open_ttl_s: int = 60         # how long OPEN state persists before HALF_OPEN


LATENCY_TIER_TIMEOUT: dict[LatencyTier, float] = {}  # populated from InvokerSettings at module init
