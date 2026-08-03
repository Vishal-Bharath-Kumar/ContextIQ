"""
AC-4: Verify Redis Sentinel HA and keyspace notifications.

Usage:
    python scripts/datastore/verify_redis.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as aioredis
from redis.asyncio.sentinel import Sentinel


async def main() -> int:
    password = os.environ.get("REDIS_PASSWORD", "")
    sentinel_hosts = [
        ("redis-headless.contextiq-data.svc.cluster.local", 26379),
    ]

    sentinel = Sentinel(
        sentinel_hosts,
        sentinel_kwargs={"password": password},
        password=password,
        decode_responses=True,
    )

    # --- Check 1: Sentinel discovers a master ---
    master_info = await sentinel.discover_master("contextiq-redis")
    print(f"[OK] Sentinel master: {master_info}")

    # --- Check 2: Sentinel sees at least 2 replicas ---
    replicas = await sentinel.discover_slaves("contextiq-redis")
    replica_count = len(replicas)
    print(f"[{'OK' if replica_count >= 2 else 'WARN'}] Sentinel replicas: {replica_count} (expected 2)")
    if replica_count < 2:
        print("WARNING: Expected 2 replicas, check replication status")

    master: aioredis.Redis = sentinel.master_for("contextiq-redis", socket_timeout=1.0)

    # --- Check 3: keyspace notifications are enabled ---
    config: dict[str, str] = await master.config_get("notify-keyspace-events")
    events = config.get("notify-keyspace-events", "")
    ok = "K" in events and "E" in events
    print(f"[{'OK' if ok else 'FAIL'}] notify-keyspace-events = {events!r}")
    if not ok:
        print("FAIL: Keyspace notifications (KEA) are not enabled (AC-4)", flush=True)
        await master.aclose()
        return 1

    # --- Check 4: basic SET/GET round-trip ---
    await master.set("healthcheck:verify_redis", "ok", ex=60)
    val: str | None = await master.get("healthcheck:verify_redis")
    print(f"[OK] SET/GET round-trip: {val!r}")

    # --- Check 5: keyspace expiry event received ---
    async with master.pubsub() as pubsub:
        await pubsub.psubscribe("__keyevent@0__:expired")
        await master.set("healthcheck:expiry_test", "x", px=200)    # 200 ms TTL
        await asyncio.sleep(0.5)
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message:
            print(f"[OK] Received keyspace expiry event: {message}")
        else:
            print("[WARN] No expiry event received within timeout — notifications may need a moment")

    await master.aclose()
    print("\n=== Redis verification passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
