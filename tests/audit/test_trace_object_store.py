"""Tests for TraceObjectStore — TASK-US034-02.

Tests use AsyncMock to stub the aiobotocore S3 client, keeping tests fast and
deterministic without requiring a running MinIO server.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError

from src.audit.trace.object_store import (
    TraceNotFoundError,
    TraceObjectStore,
    TraceObjectStoreSettings,
    TraceWriteResult,
    _apply_lifecycle_policy,
    _build_key,
    _ensure_bucket_exists,
    _ensure_versioning_enabled,
    _validate_retention,
)
from src.audit.trace.schemas import ExecutionTrace

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture()
def settings() -> TraceObjectStoreSettings:
    return TraceObjectStoreSettings(
        endpoint_url="http://localhost:9000",
        bucket="test-traces",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
        retention_days=365,
    )


@pytest.fixture()
def sample_trace() -> ExecutionTrace:
    return ExecutionTrace(
        request_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        tenant_id="tenant-abc",
        user_id="user-xyz",
        timestamp=datetime(2025, 6, 15, 10, 30, 0, tzinfo=UTC),
        prompt="How do I reset my password?",
        intent="technical_support",
    )


def _make_mock_s3(
    put_response: dict | None = None,
    get_versioning_response: dict | None = None,
    head_bucket_error: ClientError | None = None,
) -> AsyncMock:
    """Build an AsyncMock S3 client with sane defaults."""
    s3 = AsyncMock()

    s3.put_object.return_value = put_response or {
        "VersionId": "abc123",
        "ETag": '"d41d8cd98f00b204e9800998ecf8427e"',
    }
    s3.get_bucket_versioning.return_value = get_versioning_response or {"Status": ""}
    s3.put_bucket_versioning.return_value = {}
    s3.create_bucket.return_value = {}
    s3.put_bucket_lifecycle_configuration.return_value = {}

    if head_bucket_error:
        s3.head_bucket.side_effect = head_bucket_error
    else:
        s3.head_bucket.return_value = {}

    # get_object returns an async-readable body
    mock_body = AsyncMock()
    mock_body.read.return_value = b"{}"
    s3.get_object.return_value = {"Body": mock_body}

    return s3


def _client_ctx(mock_s3: AsyncMock) -> Any:  # noqa: ANN401
    """Return an async context manager that yields ``mock_s3``."""

    @asynccontextmanager
    async def _ctx(*_args: Any, **_kwargs: Any) -> AsyncGenerator[AsyncMock, None]:  # noqa: ANN401
        yield mock_s3

    return _ctx


# ------------------------------------------------------------------ #
# _build_key                                                           #
# ------------------------------------------------------------------ #


def test_build_key_format(sample_trace: ExecutionTrace) -> None:
    key = _build_key(sample_trace)
    assert key == "traces/tenant-abc/2025/06/12345678-1234-5678-1234-567812345678.json"


def test_build_key_is_deterministic(sample_trace: ExecutionTrace) -> None:
    assert _build_key(sample_trace) == _build_key(sample_trace)


def test_build_key_zero_pads_month(sample_trace: ExecutionTrace) -> None:
    trace = sample_trace.model_copy(
        update={"timestamp": datetime(2025, 3, 5, tzinfo=UTC)}
    )
    key = _build_key(trace)
    assert "/2025/03/" in key


# ------------------------------------------------------------------ #
# _validate_retention                                                  #
# ------------------------------------------------------------------ #


def test_validate_retention_raises_below_minimum() -> None:
    settings = TraceObjectStoreSettings(retention_days=89)
    with pytest.raises(ValueError, match="TRACE_STORE_RETENTION_DAYS must be >= 90"):
        _validate_retention(settings)


def test_validate_retention_passes_at_minimum() -> None:
    settings = TraceObjectStoreSettings(retention_days=90)
    _validate_retention(settings)  # must not raise


def test_validate_retention_passes_above_minimum() -> None:
    settings = TraceObjectStoreSettings(retention_days=365)
    _validate_retention(settings)  # must not raise


def test_init_raises_on_invalid_retention() -> None:
    with pytest.raises(ValueError):
        TraceObjectStore(settings=TraceObjectStoreSettings(retention_days=30))


# ------------------------------------------------------------------ #
# TraceObjectStore.write                                               #
# ------------------------------------------------------------------ #


async def test_write_returns_trace_write_result(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    mock_s3 = _make_mock_s3(put_response={"VersionId": "v1", "ETag": '"abc"'})
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        result = await store.write(sample_trace)

    assert isinstance(result, TraceWriteResult)
    assert result.object_key == _build_key(sample_trace)
    assert result.version_id == "v1"
    assert result.etag == "abc"
    assert result.written_at.tzinfo is not None


async def test_write_sets_server_side_encryption_aes256(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    mock_s3 = _make_mock_s3()
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.write(sample_trace)

    _, kwargs = mock_s3.put_object.call_args
    assert kwargs.get("ServerSideEncryption") == "AES256"


async def test_write_version_id_non_empty_when_versioning_enabled(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    mock_s3 = _make_mock_s3(put_response={"VersionId": "ver-001", "ETag": '"etag"'})
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        result = await store.write(sample_trace)

    assert result.version_id != ""


async def test_write_version_id_empty_when_versioning_disabled(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    # MinIO returns no VersionId when versioning is not enabled
    mock_s3 = _make_mock_s3(put_response={"ETag": '"etag"'})
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        result = await store.write(sample_trace)

    assert result.version_id == ""


async def test_write_strips_etag_quotes(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    mock_s3 = _make_mock_s3(put_response={"VersionId": "v1", "ETag": '"abc123"'})
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        result = await store.write(sample_trace)

    assert result.etag == "abc123"
    assert '"' not in result.etag


async def test_write_puts_to_correct_bucket_and_key(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    mock_s3 = _make_mock_s3()
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.write(sample_trace)

    _, kwargs = mock_s3.put_object.call_args
    assert kwargs["Bucket"] == settings.bucket
    assert kwargs["Key"] == _build_key(sample_trace)
    assert kwargs["ContentType"] == "application/json"


# ------------------------------------------------------------------ #
# TraceObjectStore.ensure_bucket_ready                                 #
# ------------------------------------------------------------------ #


async def test_ensure_bucket_ready_creates_bucket_when_absent(
    settings: TraceObjectStoreSettings,
) -> None:
    not_found_error = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
    )
    mock_s3 = _make_mock_s3(head_bucket_error=not_found_error)
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.ensure_bucket_ready()

    mock_s3.create_bucket.assert_awaited_once_with(Bucket=settings.bucket)


async def test_ensure_bucket_ready_enables_versioning_when_not_enabled(
    settings: TraceObjectStoreSettings,
) -> None:
    mock_s3 = _make_mock_s3(get_versioning_response={"Status": ""})
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.ensure_bucket_ready()

    mock_s3.put_bucket_versioning.assert_awaited_once_with(
        Bucket=settings.bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )


async def test_ensure_bucket_ready_skips_versioning_when_already_enabled(
    settings: TraceObjectStoreSettings,
) -> None:
    mock_s3 = _make_mock_s3(get_versioning_response={"Status": "Enabled"})
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.ensure_bucket_ready()

    mock_s3.put_bucket_versioning.assert_not_awaited()


async def test_ensure_bucket_ready_applies_lifecycle_policy(
    settings: TraceObjectStoreSettings,
) -> None:
    mock_s3 = _make_mock_s3()
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.ensure_bucket_ready()

    mock_s3.put_bucket_lifecycle_configuration.assert_awaited_once()
    _, kwargs = mock_s3.put_bucket_lifecycle_configuration.call_args
    rule = kwargs["LifecycleConfiguration"]["Rules"][0]
    assert rule["Expiration"]["Days"] == settings.retention_days
    assert rule["Filter"]["Prefix"] == "traces/"
    assert rule["Status"] == "Enabled"


async def test_ensure_bucket_ready_lifecycle_rule_id_contains_retention_days(
    settings: TraceObjectStoreSettings,
) -> None:
    mock_s3 = _make_mock_s3()
    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.ensure_bucket_ready()

    _, kwargs = mock_s3.put_bucket_lifecycle_configuration.call_args
    rule_id = kwargs["LifecycleConfiguration"]["Rules"][0]["ID"]
    assert str(settings.retention_days) in rule_id


# ------------------------------------------------------------------ #
# _apply_lifecycle_policy — idempotency                               #
# ------------------------------------------------------------------ #


async def test_apply_lifecycle_policy_is_idempotent(
    settings: TraceObjectStoreSettings,
) -> None:
    mock_s3 = AsyncMock()
    mock_s3.put_bucket_lifecycle_configuration.return_value = {}

    # Call twice — must not raise
    await _apply_lifecycle_policy(mock_s3, settings)
    await _apply_lifecycle_policy(mock_s3, settings)

    assert mock_s3.put_bucket_lifecycle_configuration.await_count == 2
    # Both calls use the same deterministic rule ID
    first_call_kwargs = mock_s3.put_bucket_lifecycle_configuration.call_args_list[0][1]
    second_call_kwargs = mock_s3.put_bucket_lifecycle_configuration.call_args_list[1][1]
    first_rule_id = first_call_kwargs["LifecycleConfiguration"]["Rules"][0]["ID"]
    second_rule_id = second_call_kwargs["LifecycleConfiguration"]["Rules"][0]["ID"]
    assert first_rule_id == second_rule_id


# ------------------------------------------------------------------ #
# TraceObjectStore.read                                                #
# ------------------------------------------------------------------ #


async def test_read_passes_version_id_when_provided(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    body_bytes = sample_trace.model_dump_json().encode()
    mock_body = AsyncMock()
    mock_body.read.return_value = body_bytes
    mock_s3 = _make_mock_s3()
    mock_s3.get_object.return_value = {"Body": mock_body}

    store = TraceObjectStore(settings=settings)
    key = _build_key(sample_trace)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.read(key, version_id="v42")

    _, kwargs = mock_s3.get_object.call_args
    assert kwargs.get("VersionId") == "v42"


async def test_read_omits_version_id_when_none(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    body_bytes = sample_trace.model_dump_json().encode()
    mock_body = AsyncMock()
    mock_body.read.return_value = body_bytes
    mock_s3 = _make_mock_s3()
    mock_s3.get_object.return_value = {"Body": mock_body}

    store = TraceObjectStore(settings=settings)
    key = _build_key(sample_trace)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        await store.read(key)

    _, kwargs = mock_s3.get_object.call_args
    assert "VersionId" not in kwargs


async def test_read_returns_execution_trace(
    settings: TraceObjectStoreSettings, sample_trace: ExecutionTrace
) -> None:
    body_bytes = sample_trace.model_dump_json().encode()
    mock_body = AsyncMock()
    mock_body.read.return_value = body_bytes
    mock_s3 = _make_mock_s3()
    mock_s3.get_object.return_value = {"Body": mock_body}

    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        result = await store.read(_build_key(sample_trace))

    assert isinstance(result, ExecutionTrace)
    assert result.request_id == sample_trace.request_id


async def test_read_raises_trace_not_found_on_no_such_key(
    settings: TraceObjectStoreSettings,
) -> None:
    no_such_key = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
        "GetObject",
    )
    mock_s3 = _make_mock_s3()
    mock_s3.get_object.side_effect = no_such_key

    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        with pytest.raises(TraceNotFoundError):
            await store.read("traces/tenant/2025/06/missing.json")


async def test_read_reraises_unexpected_client_error(
    settings: TraceObjectStoreSettings,
) -> None:
    access_denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
        "GetObject",
    )
    mock_s3 = _make_mock_s3()
    mock_s3.get_object.side_effect = access_denied

    store = TraceObjectStore(settings=settings)

    with patch("src.audit.trace.object_store._s3_client", _client_ctx(mock_s3)):
        with pytest.raises(ClientError):
            await store.read("traces/tenant/2025/06/key.json")


# ------------------------------------------------------------------ #
# _ensure_bucket_exists                                                #
# ------------------------------------------------------------------ #


async def test_ensure_bucket_exists_creates_on_404() -> None:
    not_found = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket"
    )
    mock_s3 = AsyncMock()
    mock_s3.head_bucket.side_effect = not_found
    mock_s3.create_bucket.return_value = {}

    await _ensure_bucket_exists(mock_s3, "test-bucket")

    mock_s3.create_bucket.assert_awaited_once_with(Bucket="test-bucket")


async def test_ensure_bucket_exists_no_create_when_present() -> None:
    mock_s3 = AsyncMock()
    mock_s3.head_bucket.return_value = {}

    await _ensure_bucket_exists(mock_s3, "test-bucket")

    mock_s3.create_bucket.assert_not_awaited()


async def test_ensure_bucket_exists_reraises_non_404_error() -> None:
    forbidden = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket"
    )
    mock_s3 = AsyncMock()
    mock_s3.head_bucket.side_effect = forbidden

    with pytest.raises(ClientError):
        await _ensure_bucket_exists(mock_s3, "test-bucket")


# ------------------------------------------------------------------ #
# _ensure_versioning_enabled                                           #
# ------------------------------------------------------------------ #


async def test_ensure_versioning_enabled_calls_put_when_suspended() -> None:
    mock_s3 = AsyncMock()
    mock_s3.get_bucket_versioning.return_value = {"Status": "Suspended"}
    mock_s3.put_bucket_versioning.return_value = {}

    await _ensure_versioning_enabled(mock_s3, "test-bucket")

    mock_s3.put_bucket_versioning.assert_awaited_once()


async def test_ensure_versioning_enabled_skips_put_when_already_enabled() -> None:
    mock_s3 = AsyncMock()
    mock_s3.get_bucket_versioning.return_value = {"Status": "Enabled"}

    await _ensure_versioning_enabled(mock_s3, "test-bucket")

    mock_s3.put_bucket_versioning.assert_not_awaited()
