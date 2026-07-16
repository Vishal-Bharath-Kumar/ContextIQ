"""
Custom exceptions for the ContextIQ gateway JWT authentication layer.

TASK-US004-02: Keycloak JWKS Client with Local Cache.

These exceptions are raised by :class:`~src.gateway.auth.jwks_client.JWKSClient`
and caught by :class:`~src.gateway.middleware.jwt_auth.JWTAuthMiddleware`.

Inheritance chain
-----------------
Each custom exception inherits from the corresponding ``python-jose`` exception
so that callers that catch jose exceptions directly continue to work without
modification (backward-compatible).

    ExpiredTokenError      → jose.exceptions.ExpiredSignatureError
    InvalidSignatureError  → jose.exceptions.JWSSignatureError
    MalformedTokenError    → jose.exceptions.JWTError
    ServiceUnavailableError → Exception  (not a JWT error; indicates infra failure)
"""
from __future__ import annotations

try:
    from jose.exceptions import ExpiredSignatureError as _ExpiredSignatureError
    from jose.exceptions import JWSSignatureError as _JWSSignatureError
    from jose.exceptions import JWTError as _JWTError

    class ExpiredTokenError(_ExpiredSignatureError):
        """Raised when the JWT ``exp`` claim is in the past."""

    class InvalidSignatureError(_JWSSignatureError):
        """Raised when the JWT signature does not match the JWKS public key."""

    class MalformedTokenError(_JWTError):
        """Raised for any structural JWT error: wrong algorithm, bad format, bad claims."""

except ImportError:  # pragma: no cover — only absent in stripped test envs
    class ExpiredTokenError(Exception):  # type: ignore[no-redef]
        """Raised when the JWT ``exp`` claim is in the past."""

    class InvalidSignatureError(Exception):  # type: ignore[no-redef]
        """Raised when the JWT signature does not match the JWKS public key."""

    class MalformedTokenError(Exception):  # type: ignore[no-redef]
        """Raised for any structural JWT error."""


class ServiceUnavailableError(Exception):
    """
    Raised when the Keycloak JWKS endpoint is unreachable and no valid cached
    keys are available (not even within the stale-cache grace period).

    Middleware maps this to HTTP 503 with ``Retry-After: 30``.
    """
