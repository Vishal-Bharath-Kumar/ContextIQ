"""LangGraph AsyncRedisSaver checkpointer with 1-hour TTL for AgentState persistence.

TASK-US005-03: Wire LangGraph AsyncRedisSaver Checkpointer for State Persistence.

Provides:
- ``TTLRedisSaver`` — AsyncRedisSaver subclass that enforces a 1-hour (3 600 s) TTL
  on every checkpoint key via the native ``ttl`` configuration dict.
- ``get_redis_checkpointer()`` — async factory used by the Agent Worker lifespan to
  initialise the checkpointer once and store it on ``app.state``.
"""
from __future__ import annotations

import logging
import os
from typing import ClassVar

from langgraph.checkpoint.redis.aio import AsyncRedisSaver

logger = logging.getLogger(__name__)

# 1-hour TTL expressed in minutes (AsyncRedisSaver's ttl config uses minutes).
_TTL_MINUTES: float = 60.0


class TTLRedisSaver(AsyncRedisSaver):
    """AsyncRedisSaver with a fixed 1-hour TTL on every checkpoint key.

    The native ``ttl`` constructor parameter accepts a dict with a
    ``"default_ttl"`` key expressed **in minutes**.  This subclass hard-wires
    the value so callers cannot accidentally omit it.
    """

    TTL_SECONDS: ClassVar[int] = 3600

    def __init__(
        self,
        redis_url: str | None = None,
        **kwargs: object,
    ) -> None:
        # Merge caller-supplied ttl (if any) with our mandatory default_ttl.
        ttl_cfg: dict[str, object] = {"default_ttl": _TTL_MINUTES}
        if "ttl" in kwargs and isinstance(kwargs["ttl"], dict):
            ttl_cfg.update(kwargs.pop("ttl"))  # type: ignore[arg-type]
        else:
            kwargs.pop("ttl", None)

        super().__init__(redis_url=redis_url, ttl=ttl_cfg, **kwargs)

    async def aclose(self) -> None:
        """Close the underlying Redis connection cleanly."""
        await self.__aexit__(None, None, None)


async def get_redis_checkpointer() -> TTLRedisSaver:
    """Construct, set up, and return the singleton TTLRedisSaver.

    Reads ``REDIS_URL`` from the environment (e.g. ``redis://redis:6379/0``).
    Raises ``RuntimeError`` on connection / setup failure so the Agent Worker
    process fails fast at startup rather than silently degrading.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    logger.info("checkpointer: connecting to Redis at %s", redis_url)
    checkpointer = TTLRedisSaver(redis_url=redis_url)
    try:
        await checkpointer.setup()
    except Exception as exc:
        logger.exception("checkpointer: Redis setup failed — cannot start")
        raise RuntimeError(
            f"Failed to initialise Redis checkpointer at {redis_url!r}: {exc}"
        ) from exc
    logger.info(
        "checkpointer: ready (TTL=%d s, default_ttl=%.0f min)",
        TTLRedisSaver.TTL_SECONDS,
        _TTL_MINUTES,
    )
    return checkpointer
