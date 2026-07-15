"""
AC-5: Create contextiq-traces bucket with versioning and lifecycle rules.
Also creates contextiq-audit-archive (US-044), contextiq-models,
contextiq-embeddings, and contextiq-postgres-backups.
Idempotent.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile


MINIO_ALIAS    = "contextiq"
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "https://minio.contextiq-infra.svc.cluster.local:9000")
MINIO_USER     = os.environ.get("MINIO_ROOT_USER",     "")
MINIO_PASSWORD = os.environ.get("MINIO_ROOT_PASSWORD", "")


def mc(*args: str) -> dict[str, object]:
    """Run a MinIO Client command and return parsed JSON from the first output line."""
    cmd = ["mc", "--json"] + list(args)
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    output = result.stdout.decode().strip()
    if result.returncode != 0:
        stderr = result.stderr.decode()
        raise RuntimeError(
            f"mc command failed: {' '.join(args)}\nstderr: {stderr}\nstdout: {output}"
        )
    first_line = output.split("\n")[0] if output else "{}"
    return json.loads(first_line) if first_line else {}


# ---------------------------------------------------------------------------
# Bucket definitions
# ---------------------------------------------------------------------------

BUCKETS: list[dict[str, object]] = [
    {
        "name":       "contextiq-traces",
        "versioning": True,
        # AC-5: 90-day cold transition, 1-year expiry
        "lifecycle": {
            "Rules": [
                {
                    "ID":     "contextiq-traces-cold-90d",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Transition": {"Days": 90, "StorageClass": "GLACIER"},
                },
                {
                    "ID":         "contextiq-traces-expire-1y",
                    "Status":     "Enabled",
                    "Filter":     {"Prefix": ""},
                    "Expiration": {"Days": 365},
                },
            ]
        },
    },
    {
        "name":       "contextiq-audit-archive",    # US-044 (TASK-US044-03)
        "versioning": True,
        "lifecycle": {
            "Rules": [
                {
                    "ID":         "audit-archive-expire-3y",
                    "Status":     "Enabled",
                    "Filter":     {"Prefix": ""},
                    "Expiration": {"Days": 1096},
                },
            ]
        },
    },
    {"name": "contextiq-models",     "versioning": True,  "lifecycle": None},
    {"name": "contextiq-embeddings", "versioning": False, "lifecycle": None},
    {
        "name":       "contextiq-postgres-backups",    # US-050 (TASK-US050-01)
        "versioning": False,
        "lifecycle": {
            "Rules": [
                {
                    "ID":         "postgres-backups-expire-30d",
                    "Status":     "Enabled",
                    "Filter":     {"Prefix": "daily/"},
                    "Expiration": {"Days": 30},
                },
            ]
        },
    },
]


def apply_lifecycle(bucket_alias_path: str, lifecycle: dict[str, object]) -> None:
    """Write lifecycle JSON to a temp file and import it into the bucket."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
        json.dump(lifecycle, fh)
        tmp_path = fh.name
    try:
        mc("ilm", "import", bucket_alias_path, tmp_path)
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)


def main() -> int:
    if not MINIO_USER or not MINIO_PASSWORD:
        print("ERROR: MINIO_ROOT_USER / MINIO_ROOT_PASSWORD not set", flush=True)
        return 1

    # Register alias — --api s3v4 required for MinIO auth compatibility
    mc("alias", "set", "--api", "s3v4", MINIO_ALIAS, MINIO_ENDPOINT, MINIO_USER, MINIO_PASSWORD)
    print(f"MinIO alias set: {MINIO_ALIAS} → {MINIO_ENDPOINT}")

    for bucket in BUCKETS:
        name: str = bucket["name"]  # type: ignore[assignment]

        # Create bucket (idempotent via --ignore-existing)
        try:
            mc("mb", "--ignore-existing", f"{MINIO_ALIAS}/{name}")
            print(f"  [OK] Bucket {name} exists or created.")
        except RuntimeError as exc:
            print(f"  [FAIL] Could not create bucket {name}: {exc}")
            return 1

        # Enable SSE-S3 encryption (AC-5, TASK-US048-04)
        mc("encrypt", "set", "SSE-S3", f"{MINIO_ALIAS}/{name}")
        print(f"  [OK] SSE-S3 enabled on {name}.")

        # Enable versioning where required
        if bucket.get("versioning"):
            mc("version", "enable", f"{MINIO_ALIAS}/{name}")
            print(f"  [OK] Versioning enabled on {name}.")

        # Apply lifecycle rules where defined
        lifecycle = bucket.get("lifecycle")
        if lifecycle is not None:
            apply_lifecycle(f"{MINIO_ALIAS}/{name}", lifecycle)  # type: ignore[arg-type]
            print(f"  [OK] Lifecycle rules applied to {name}.")

    print("\n=== MinIO bootstrap complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
