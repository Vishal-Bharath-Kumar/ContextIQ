"""
Redis client factory using Sentinel for HA discovery.
AC-4: connects via Sentinel which transparently routes to the current primary.
"""
from __future__ import annotations

import os

import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel

# Sentinel endpoints — comma-separated host:port pairs
# Default points at the Bitnami Redis headless Service which routes to all Sentinel pods
_SENTINEL_HOSTS_RAW = os.environ.get(
    "REDIS_SENTINEL_HOSTS",
    "redis-headless.contextiq-data.svc.cluster.local:26379",
)
_SENTINEL_MASTER = os.environ.get("REDIS_SENTINEL_MASTER", "contextiq-redis")


def create_redis_client() -> aioredis.Redis:
    """Return an async Redis client via Sentinel for HA (AC-4)."""
    password = os.environ.get("REDIS_PASSWORD", "")
    sentinel_hosts = [
        (h.split(":")[0], int(h.split(":")[1]))
        for h in _SENTINEL_HOSTS_RAW.split(",")
    ]

    # sentinel_kwargs apply to the Sentinel monitor connections (port 26379)
    # Top-level TLS kwargs apply to the Redis data connections (port 6379)
    sentinel = Sentinel(
        sentinel_hosts,
        sentinel_kwargs={
            "password":     password,
            "ssl":          True,
            "ssl_certfile": "/tls/tls.crt",
            "ssl_keyfile":  "/tls/tls.key",
            "ssl_ca_certs": "/tls/ca.crt",    # verify sentinel TLS certificate
        },
        password=password,
        ssl=True,
        ssl_certfile="/tls/tls.crt",
        ssl_keyfile="/tls/tls.key",
        ssl_ca_certs="/tls/ca.crt",
        decode_responses=True,
    )
    # master_for returns a Redis client that always points at the Sentinel-elected primary
    return sentinel.master_for(_SENTINEL_MASTER, socket_timeout=0.5)


def create_redis_subscriber() -> aioredis.Redis:
    """
    Return a dedicated Redis client for PubSub / keyspace notification subscriptions.
    AC-4: subscribe to __keyevent@*__:expired for cache invalidation events.
    A separate client is needed because a PubSub connection cannot mix with regular commands.
    """
    return create_redis_client()
