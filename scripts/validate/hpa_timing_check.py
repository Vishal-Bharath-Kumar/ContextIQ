"""
AC-4: Confirms that:
1. Scale-UP occurs within 30 s of load starting.
2. Scale-DOWN does NOT occur within 300 s of load stopping (stabilization window).

Usage:
    python scripts/validate/hpa_timing_check.py \
        --namespace contextiq-agents \
        --hpa-name release-name-agent-worker \
        --expected-min-replicas 3 \
        --scale-up-deadline 30 \
        --scale-down-hold 300

Exit code 0 = all assertions passed.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _get_hpa_replicas(namespace: str, hpa_name: str) -> int:
    result = subprocess.run(
        ["kubectl", "get", "hpa", hpa_name, "-n", namespace, "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    data: dict[str, Any] = json.loads(result.stdout)
    status: dict[str, Any] = data.get("status", {})
    return int(status.get("currentReplicas", 0))


def wait_for_scale_up(
    namespace:             str,
    hpa_name:              str,
    expected_min_replicas: int,
    deadline_seconds:      int,
) -> bool:
    """
    AC-4: Poll until replica count >= expected_min_replicas or deadline exceeded.
    Returns True if scale-up observed within deadline.
    """
    start = time.monotonic()
    while time.monotonic() - start < deadline_seconds:
        replicas = _get_hpa_replicas(namespace, hpa_name)
        logger.info("  current replicas: %d (want >= %d)", replicas, expected_min_replicas)
        if replicas >= expected_min_replicas:
            elapsed = time.monotonic() - start
            logger.info("Scale-up confirmed in %.1f s (deadline: %d s)", elapsed, deadline_seconds)
            return True
        time.sleep(5)
    return False


def assert_no_scale_down(
    namespace:     str,
    hpa_name:      str,
    initial_count: int,
    hold_seconds:  int,
) -> bool:
    """
    AC-4: Assert replica count does NOT drop for hold_seconds after load stops.
    Returns True if no scale-down occurred during the hold window.
    """
    logger.info(
        "Monitoring for unwanted scale-down for %d s (initial replicas: %d)…",
        hold_seconds, initial_count,
    )
    start = time.monotonic()
    while time.monotonic() - start < hold_seconds:
        replicas = _get_hpa_replicas(namespace, hpa_name)
        if replicas < initial_count:
            logger.error(
                "FAIL: scale-down observed after %.0f s (replicas dropped from %d to %d)",
                time.monotonic() - start, initial_count, replicas,
            )
            return False
        time.sleep(15)
    logger.info(
        "No premature scale-down within %d s — stabilization window respected.", hold_seconds,
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="HPA timing assertion")
    parser.add_argument("--namespace",              required=True)
    parser.add_argument("--hpa-name",               required=True)
    parser.add_argument("--expected-min-replicas",  type=int, required=True)
    parser.add_argument("--scale-up-deadline",      type=int, default=30)
    parser.add_argument("--scale-down-hold",        type=int, default=300)
    args = parser.parse_args()

    logger.info("=== HPA scale-up timing check ===")
    scaled_up = wait_for_scale_up(
        args.namespace, args.hpa_name,
        args.expected_min_replicas, args.scale_up_deadline,
    )
    if not scaled_up:
        logger.error("FAIL: scale-up did not occur within %d s", args.scale_up_deadline)
        return 1

    peak_replicas = _get_hpa_replicas(args.namespace, args.hpa_name)
    logger.info("=== Scale-down stabilization check (hold: %d s) ===", args.scale_down_hold)
    no_early_down = assert_no_scale_down(
        args.namespace, args.hpa_name, peak_replicas, args.scale_down_hold,
    )
    return 0 if no_early_down else 1


if __name__ == "__main__":
    sys.exit(main())
