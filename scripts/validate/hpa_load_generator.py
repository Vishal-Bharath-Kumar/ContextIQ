"""
Drives concurrent requests to the Agent Worker endpoint to raise
contextiq_active_requests above the HPA threshold (5 per pod).

Usage:
    python scripts/validate/hpa_load_generator.py \
        --target http://mcp-gateway.contextiq-gateway.svc.cluster.local \
        --concurrency 50 \
        --duration 120

The script fires concurrent requests and keeps them in-flight long enough
for Prometheus to scrape the elevated gauge value and for the HPA to react.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def _flood_worker(
    client:  httpx.AsyncClient,
    url:     str,
    stop_at: float,
    results: list[int],
) -> None:
    """Single worker: keep sending requests until stop_at epoch."""
    while time.time() < stop_at:
        try:
            response = await client.post(
                url,
                json={"query": "load test", "session_id": "hpa-test"},
                timeout=30.0,
            )
            results.append(response.status_code)
        except Exception:
            results.append(-1)
        await asyncio.sleep(0.1)    # slight back-off to avoid overwhelming the service


async def run(target: str, concurrency: int, duration: int) -> None:
    stop_at = time.time() + duration
    results: list[int] = []

    # verify=False only relevant for HTTPS; internal .svc.cluster.local URLs use HTTP
    async with httpx.AsyncClient(verify=False) as client:  # noqa: S501
        tasks = [
            asyncio.create_task(
                _flood_worker(client, f"{target}/tools/context_query", stop_at, results)
            )
            for _ in range(concurrency)
        ]
        await asyncio.gather(*tasks)

    ok = sum(1 for r in results if r == 200)
    total = len(results)
    logger.info(
        "Load test complete — %d/%d requests succeeded (%.1f%%)",
        ok, total, 100.0 * ok / max(total, 1),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HPA load generator")
    parser.add_argument("--target",      default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--duration",    type=int, default=120)
    args = parser.parse_args()
    asyncio.run(run(args.target, args.concurrency, args.duration))
