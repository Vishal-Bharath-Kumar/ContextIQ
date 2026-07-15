#!/usr/bin/env python3
"""CI validation script for Trivy security scan artifacts.

Modes
-----
--validate-ignores FILE
    Verify every active .trivyignore entry has a valid, non-expired
    exp:YYYY-MM-DD tag.  Fails (exit 1) if any entry is missing an expiry
    date or the expiry date has already passed.

--check-sarif FILE
    Parse a Trivy SARIF output file and exit non-zero if any HIGH/CRITICAL
    (SARIF level=error) findings are present.

Usage in GitHub Actions
-----------------------
  # Validate before the scan so expired suppressions are caught immediately
  python3 scripts/ci/check_trivy_results.py --validate-ignores .trivyignore

  # Optionally re-check the SARIF after the scan for custom logic
  python3 scripts/ci/check_trivy_results.py --check-sarif trivy-results.sarif
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Matches "exp:YYYY-MM-DD" anywhere on the line (case-insensitive)
_EXP_RE = re.compile(r"\bexp:(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)


def validate_ignores(ignore_file: Path) -> int:
    """Return 1 (failure) if any active ignore entry lacks or has an expired expiry."""
    if not ignore_file.exists():
        print(f"::warning file={ignore_file}::{ignore_file} not found — nothing to validate.")
        return 0

    errors: list[str] = []
    today = date.today()

    for lineno, raw in enumerate(ignore_file.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()

        # Skip blank lines and pure-comment lines (lines that start with #)
        if not line or line.startswith("#"):
            continue

        # This is an active suppression line, e.g.:
        #   CVE-2024-12345                            ← missing expiry → ERROR
        #   CVE-2024-12345 # exp:2026-10-01; reason   ← valid inline comment form
        exp_match = _EXP_RE.search(raw)  # search raw line including comments
        if not exp_match:
            errors.append(
                f"Line {lineno}: active ignore entry is missing a required "
                f"exp:YYYY-MM-DD expiry date — add 'exp:YYYY-MM-DD' and a "
                f"justification comment. Entry: {raw!r}"
            )
            continue

        try:
            expiry = datetime.strptime(exp_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            errors.append(
                f"Line {lineno}: unparseable expiry date {exp_match.group(1)!r} "
                f"(expected YYYY-MM-DD). Entry: {raw!r}"
            )
            continue

        if expiry < today:
            errors.append(
                f"Line {lineno}: ignore entry expired on {expiry} "
                f"({(today - expiry).days} day(s) ago) — review and either remove "
                f"or extend the suppression. Entry: {raw!r}"
            )

    if errors:
        print(
            f"::error::{ignore_file}: trivyignore validation failed "
            f"({len(errors)} error(s)):",
            file=sys.stderr,
        )
        for msg in errors:
            print(f"  {msg}", file=sys.stderr)
        return 1

    print(
        f"trivyignore validation passed ({ignore_file}): "
        f"all active entries have valid, non-expired expiry dates."
    )
    return 0


def check_sarif(sarif_file: Path) -> int:
    """Return 1 (failure) if any HIGH/CRITICAL finding exists in the SARIF file."""
    if not sarif_file.exists():
        print(f"::error::{sarif_file} not found.", file=sys.stderr)
        return 1

    data: dict = json.loads(sarif_file.read_text(encoding="utf-8"))
    findings: list[str] = []

    for run in data.get("runs", []):
        for result in run.get("results", []):
            # SARIF level "error" maps to HIGH/CRITICAL from Trivy
            if result.get("level") == "error":
                rule_id = result.get("ruleId", "UNKNOWN")
                message = result.get("message", {}).get("text", "no description")
                # Collect first location for context
                locations = result.get("locations", [])
                loc_str = ""
                if locations:
                    phys = locations[0].get("physicalLocation", {})
                    art = phys.get("artifactLocation", {}).get("uri", "")
                    region = phys.get("region", {})
                    line = region.get("startLine", "")
                    loc_str = f" [{art}:{line}]" if art else ""
                findings.append(f"{rule_id}{loc_str}: {message}")

    if findings:
        print(
            f"::error::Trivy found {len(findings)} HIGH/CRITICAL vulnerability(ies) "
            f"in {sarif_file}:",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"Trivy SARIF check passed: no HIGH/CRITICAL findings in {sarif_file}.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--validate-ignores",
        metavar="FILE",
        type=Path,
        help="Validate .trivyignore expiry dates (e.g. .trivyignore)",
    )
    group.add_argument(
        "--check-sarif",
        metavar="FILE",
        type=Path,
        help="Check a Trivy SARIF output file for HIGH/CRITICAL findings",
    )
    args = parser.parse_args()

    if args.validate_ignores:
        sys.exit(validate_ignores(args.validate_ignores))
    else:
        sys.exit(check_sarif(args.check_sarif))


if __name__ == "__main__":
    main()
