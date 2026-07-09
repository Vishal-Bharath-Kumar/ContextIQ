# TASK-US004-04 — Audit Logging for Authentication Failures

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US004-04 |
| User Story | US-004 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Observability / Security |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Emit a structured audit log entry for every authentication failure that includes the user-agent, client IP, timestamp, and failure reason. Logs must be machine-parseable, forwarded to Loki, and queryable for security investigations — without logging any token value (even partial).

## Implementation Details

**Technology:** Python 3.11+, `structlog`, Loki (via Promtail / Alloy log shipper)

**File locations:**
- `src/gateway/middleware/jwt_auth.py` — audit log calls added at each rejection path
- `src/gateway/audit/auth_audit.py` — `log_auth_failure()` function
- `tests/gateway/test_auth_audit_logging.py`

**`log_auth_failure()` function:**
```python
import structlog

audit_logger = structlog.get_logger("contextiq.audit.auth")

def log_auth_failure(
    *,
    reason: str,           # missing_token | malformed_token | invalid_signature | token_expired
    ip_address: str,
    user_agent: str,
    path: str,
    method: str,
    timestamp: str,        # ISO-8601 UTC
) -> None:
    audit_logger.warning(
        "authentication_failure",
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
        path=path,
        method=method,
        timestamp=timestamp,
        event_type="auth.failure",
    )
```

**IP extraction** (handle X-Forwarded-For from NGINX ingress):
```python
def _get_client_ip(scope: Scope) -> str:
    headers = dict(scope.get("headers", []))
    xff = headers.get(b"x-forwarded-for", b"").decode()
    if xff:
        return xff.split(",")[0].strip()   # leftmost = original client
    client = scope.get("client")
    return client[0] if client else "unknown"
```

**Security rules for log content:**
- NEVER log the token string or any substring of it (even truncated) — prevents token leakage in log aggregation pipelines
- Log only: reason, IP, user-agent, path, HTTP method, timestamp
- `user_agent` is truncated to 256 characters to prevent log injection via crafted headers

**Log injection prevention** (OWASP A03 — Injection):
```python
user_agent = (scope_headers.get(b"user-agent", b"").decode()[:256]
              .replace("\n", "").replace("\r", ""))
```

**Loki label strategy:**
- Labels (low-cardinality): `service=contextiq-gateway`, `event_type=auth.failure`, `env=staging|production`
- Log-line fields (high-cardinality): `ip_address`, `user_agent`, `path`, `reason`

**Prometheus counter for alerting:**
```python
auth_failures_total = Counter(
    "contextiq_auth_failures_total",
    "Authentication failures by reason",
    ["reason"]
)
# Increment alongside every audit log call
auth_failures_total.labels(reason=reason).inc()
```

**Grafana alert:** Fire when `rate(contextiq_auth_failures_total[5m]) > 10` (potential brute-force or misconfigured client).

## Acceptance Criteria

- [ ] Every `HTTP 401` and `HTTP 403` from the auth middleware produces a structured `authentication_failure` log entry
- [ ] Log entry contains exactly: `reason`, `ip_address`, `user_agent`, `path`, `method`, `timestamp` — no token content
- [ ] `X-Forwarded-For` header is used to extract the real client IP when present
- [ ] Newlines and carriage returns stripped from `user_agent` before logging (log injection prevention)
- [ ] `contextiq_auth_failures_total{reason="token_expired"}` counter increments on each expired-token rejection
- [ ] Unit tests assert: log fields present, token value absent, user-agent sanitisation, IP extraction from XFF

## Dependencies

- TASK-US004-01 (middleware rejection paths — call `log_auth_failure()` at each rejection)
- US-036 (Prometheus scraping)
- EP-TECH-001 (Promtail/Alloy configured to ship gateway logs to Loki)

## Definition of Done

- [ ] `structlog` added to `pyproject.toml`; configured with JSON renderer for production
- [ ] Unit test asserts no token substring present in captured log output (parametrised with real token fixture)
- [ ] Loki query `{service="contextiq-gateway", event_type="auth.failure"}` returns results in staging
- [ ] Grafana "Auth Failure Rate" panel and brute-force alert rule merged into Helm chart
