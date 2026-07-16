"""
TASK-US004-04: Structured audit logging for authentication failures.

Emits a machine-parseable ``authentication_failure`` log entry for every
JWT rejection in the gateway.  Log fields are intentionally minimal to
prevent token leakage in log-aggregation pipelines (OWASP A09 — Security
Logging and Monitoring Failures).

Loki label strategy
-------------------
Low-cardinality (Loki labels): ``service``, ``event_type``, ``env``
High-cardinality (log-line fields): ``ip_address``, ``user_agent``,
    ``path``, ``reason``

Prometheus counter
------------------
``contextiq_auth_failures_total{reason=...}`` — used by the Grafana
brute-force alert: ``rate(contextiq_auth_failures_total[5m]) > 10``
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from prometheus_client import Counter

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Structured audit logger — JSON renderer configured at app startup.
# ---------------------------------------------------------------------------
_audit_logger = structlog.get_logger("contextiq.audit.auth")

# ---------------------------------------------------------------------------
# Prometheus counter — incremented alongside every audit log call.
# ---------------------------------------------------------------------------
auth_failures_total = Counter(
    "contextiq_auth_failures_total",
    "Authentication failures by reason",
    ["reason"],
)

# ---------------------------------------------------------------------------
# Valid reason literals (mirrors jwt_auth.py rejection paths)
# ---------------------------------------------------------------------------
_VALID_REASONS = frozenset({
    "missing_token",
    "invalid_token_format",
    "malformed_token",
    "invalid_signature",
    "token_expired",
})


def _get_client_ip(scope: dict[str, Any]) -> str:
    """Extract the real client IP, preferring X-Forwarded-For (NGINX ingress).

    The leftmost address in X-Forwarded-For is the original client IP.
    Falls back to the ASGI ``client`` tuple when the header is absent.
    """
    headers: dict[bytes, bytes] = dict(scope.get("headers", []))
    xff = headers.get(b"x-forwarded-for", b"").decode("latin-1")
    if xff:
        return xff.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _sanitise_user_agent(scope: dict[str, Any]) -> str:
    """Return a sanitised User-Agent string (OWASP A03 — Injection).

    - Truncated to 256 chars to bound log-line size.
    - Newlines and carriage returns stripped to prevent log injection via
      crafted ``User-Agent`` headers.
    """
    headers: dict[bytes, bytes] = dict(scope.get("headers", []))
    raw = headers.get(b"user-agent", b"").decode("latin-1", errors="replace")
    return raw[:256].replace("\n", "").replace("\r", "")


def log_auth_failure(
    *,
    reason: str,
    ip_address: str,
    user_agent: str,
    path: str,
    method: str,
    timestamp: str,
) -> None:
    """Emit a structured ``authentication_failure`` audit log entry and
    increment the Prometheus failure counter.

    Parameters
    ----------
    reason:
        One of: ``missing_token``, ``invalid_token_format``,
        ``malformed_token``, ``invalid_signature``, ``token_expired``.
    ip_address:
        Real client IP (resolved from X-Forwarded-For when present).
    user_agent:
        Sanitised User-Agent string (newlines stripped, max 256 chars).
    path:
        Request path (e.g. ``/mcp/sse``).
    method:
        HTTP method (e.g. ``GET``).
    timestamp:
        ISO-8601 UTC timestamp of the failure.

    Security note
    -------------
    This function MUST NOT receive or log the token value — not even a
    truncated substring.  Callers in ``jwt_auth.py`` are responsible for
    ensuring the token is not passed here.
    """
    _audit_logger.warning(
        "authentication_failure",
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
        path=path,
        method=method,
        timestamp=timestamp,
        event_type="auth.failure",
    )
    auth_failures_total.labels(reason=reason).inc()
