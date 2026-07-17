"""Unit tests for RegoValidator — TASK-US033-02.

Uses respx (httpx mock) to simulate OPA responses without a real OPA sidecar.
"""
from __future__ import annotations

import httpx
import pytest
import respx

from src.governance.policy.validator import (
    RegoValidationError,
    RegoValidationResult,
    RegoValidator,
)

_OPA_BASE = "http://localhost:8181"
_VALID_REGO = "package acl\n\nallow = true\n"
_INVALID_REGO = "package acl\n\nallow =\n"  # syntax error — missing RHS

_TRANSIENT_URL_PREFIX = f"{_OPA_BASE}/v1/policies/_rego_validation_"


# ------------------------------------------------------------------ #
# validate() — success path                                           #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
@respx.mock
async def test_validate_returns_valid_on_opa_200():
    policy_name = "test_policy"
    url = f"{_TRANSIENT_URL_PREFIX}{policy_name}"

    respx.put(url).mock(return_value=httpx.Response(200, json={"result": {}}))
    respx.delete(url).mock(return_value=httpx.Response(200))

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client, opa_base=_OPA_BASE)
        result = await validator.validate(policy_name, _VALID_REGO)

    assert result.is_valid is True
    assert result.errors == []


@pytest.mark.asyncio
@respx.mock
async def test_validate_deletes_transient_policy_after_success():
    policy_name = "cleanup_test"
    url = f"{_TRANSIENT_URL_PREFIX}{policy_name}"

    put_route = respx.put(url).mock(return_value=httpx.Response(200, json={}))
    delete_route = respx.delete(url).mock(return_value=httpx.Response(200))

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client, opa_base=_OPA_BASE)
        await validator.validate(policy_name, _VALID_REGO)

    assert put_route.called
    assert delete_route.called


# ------------------------------------------------------------------ #
# validate() — failure path (AC-6)                                   #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
@respx.mock
async def test_validate_returns_invalid_on_opa_400_with_errors_array():
    policy_name = "bad_policy"
    url = f"{_TRANSIENT_URL_PREFIX}{policy_name}"

    opa_error_body = {
        "code": "invalid_parameter",
        "message": "error(s) occurred while compiling module(s)",
        "errors": [
            {"message": "unexpected token =", "location": {}},
            {"message": "missing expression after assign", "location": {}},
        ],
    }
    respx.put(url).mock(return_value=httpx.Response(400, json=opa_error_body))

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client, opa_base=_OPA_BASE)
        result = await validator.validate(policy_name, _INVALID_REGO)

    assert result.is_valid is False
    assert "unexpected token =" in result.errors
    assert "missing expression after assign" in result.errors


@pytest.mark.asyncio
@respx.mock
async def test_validate_returns_invalid_on_opa_400_with_message_only():
    policy_name = "bad_policy_msg"
    url = f"{_TRANSIENT_URL_PREFIX}{policy_name}"

    respx.put(url).mock(
        return_value=httpx.Response(400, json={"message": "parse error near line 3"})
    )

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client, opa_base=_OPA_BASE)
        result = await validator.validate(policy_name, _INVALID_REGO)

    assert result.is_valid is False
    assert result.errors == ["parse error near line 3"]


@pytest.mark.asyncio
@respx.mock
async def test_validate_does_not_delete_after_failure():
    """Transient policy is NOT deleted if OPA rejected it (it was never stored)."""
    policy_name = "error_policy"
    url = f"{_TRANSIENT_URL_PREFIX}{policy_name}"

    respx.put(url).mock(
        return_value=httpx.Response(400, json={"message": "parse error"})
    )
    # DELETE should not be called; if it is, respx will raise an error
    # because there is no registered DELETE route.

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client, opa_base=_OPA_BASE)
        result = await validator.validate(policy_name, _INVALID_REGO)

    assert result.is_valid is False


@pytest.mark.asyncio
@respx.mock
async def test_validate_handles_non_json_opa_response():
    policy_name = "non_json_policy"
    url = f"{_TRANSIENT_URL_PREFIX}{policy_name}"

    respx.put(url).mock(return_value=httpx.Response(503, text="Service Unavailable"))

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client, opa_base=_OPA_BASE)
        result = await validator.validate(policy_name, _VALID_REGO)

    assert result.is_valid is False
    assert len(result.errors) == 1
    assert "503" in result.errors[0]


# ------------------------------------------------------------------ #
# RegoValidationResult helpers                                        #
# ------------------------------------------------------------------ #


def test_error_detail_joins_errors():
    result = RegoValidationResult(is_valid=False, errors=["err1", "err2"])
    assert result.error_detail == "err1; err2"


def test_error_detail_empty_when_valid():
    result = RegoValidationResult(is_valid=True)
    assert result.error_detail == ""


# ------------------------------------------------------------------ #
# RegoValidationError                                                 #
# ------------------------------------------------------------------ #


def test_rego_validation_error_stores_errors():
    errors = ["syntax error at line 3", "undefined ref: data.x"]
    exc = RegoValidationError(errors)

    assert exc.errors == errors
    assert "syntax error at line 3" in str(exc)
    assert "undefined ref: data.x" in str(exc)


# ------------------------------------------------------------------ #
# TASK-US033-05 — AC-6: RegoValidator surfaces OPA errors            #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_rego_validator_returns_errors_from_opa(mock_opa_invalid):
    """AC-6: RegoValidator surfaces OPA 400 errors as RegoValidationResult.errors."""
    from tests.governance.conftest import POLICY_NAME, INVALID_REGO

    async with httpx.AsyncClient() as client:
        validator = RegoValidator(client=client, opa_base=_OPA_BASE)
        result = await validator.validate(POLICY_NAME, INVALID_REGO)

    assert result.is_valid is False
    assert len(result.errors) > 0
    assert any(
        "parse" in e.lower() or "error" in e.lower()
        for e in result.errors
    )
