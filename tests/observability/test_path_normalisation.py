from __future__ import annotations

import pytest

from src.observability.metrics.middleware import _normalise_path


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "/v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "/v1/traces/{id}",
        ),
        (
            "/v1/knowledge-sources/42/sync",
            "/v1/knowledge-sources/{id}/sync",
        ),
        (
            "/v1/policies",
            "/v1/policies",
        ),
        (
            "/v1/traces/3fa85f64-5717-4562-b3fc-2c963f66afa6/export",
            "/v1/traces/{id}/export",
        ),
        (
            "/healthz",
            "/healthz",
        ),
    ],
)
def test_normalise_path(raw: str, expected: str) -> None:
    assert _normalise_path(raw) == expected
