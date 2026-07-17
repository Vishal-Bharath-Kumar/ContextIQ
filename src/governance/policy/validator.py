"""RegoValidator — OPA-backed syntax/compile check for Rego source.

Uses PUT /v1/policies/{transient_name} to validate Rego, then cleans up with
DELETE. Returns structured results; the call site decides whether to raise.

Satisfies AC-6 (422 on invalid Rego).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class RegoValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)

    @property
    def error_detail(self) -> str:
        return "; ".join(self.errors)


class RegoValidationError(Exception):
    """Raised when candidate Rego fails OPA syntax/compile check.

    The ``errors`` attribute contains the raw OPA error messages (AC-6).
    """

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class RegoValidator:
    """Validates Rego source via OPA's PUT /v1/policies/{name} endpoint.

    A transient policy is PUT to OPA; if OPA accepts it (HTTP 200) the policy
    is immediately removed with DELETE. Parse/compile errors (HTTP 400) are
    extracted and returned in the result.
    """

    _TRANSIENT_POLICY_PREFIX = "_rego_validation_"

    def __init__(
        self,
        client: httpx.AsyncClient,
        opa_base: str = "http://localhost:8181",
    ) -> None:
        self._client = client
        self._opa_base = opa_base.rstrip("/")

    async def validate(self, name: str, rego_body: str) -> RegoValidationResult:
        """Submit Rego to OPA for syntax/compile validation.

        Returns ``RegoValidationResult(is_valid=True)`` on success.
        Returns ``RegoValidationResult(is_valid=False, errors=[...])`` on failure.
        Does NOT raise — the call site decides whether to raise ``RegoValidationError``.
        """
        transient_name = f"{self._TRANSIENT_POLICY_PREFIX}{name}"
        url = f"{self._opa_base}/v1/policies/{transient_name}"

        put_response = await self._client.put(
            url,
            content=rego_body.encode(),
            headers={"Content-Type": "text/plain"},
            timeout=5.0,
        )

        if put_response.status_code == 200:
            await self._client.delete(url, timeout=2.0)
            return RegoValidationResult(is_valid=True)

        errors = _extract_opa_errors(put_response)
        return RegoValidationResult(is_valid=False, errors=errors)


def _extract_opa_errors(response: httpx.Response) -> list[str]:
    """Parse an OPA error response body.

    Expected shape: ``{"code": "invalid_parameter", "message": "...", "errors": [...]}``
    """
    try:
        body = response.json()
    except Exception:
        return [f"OPA returned HTTP {response.status_code}: {response.text[:256]}"]

    if "errors" in body and isinstance(body["errors"], list):
        return [e.get("message") or str(e) for e in body["errors"]]
    if "message" in body:
        return [body["message"]]
    return [f"OPA returned HTTP {response.status_code}"]
