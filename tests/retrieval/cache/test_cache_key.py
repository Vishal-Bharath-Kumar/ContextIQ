"""Unit tests for cache key derivation: ContextCacheKey and make_cache_key."""

from __future__ import annotations

import re

from src.retrieval.cache.cache_key import (
    ContextCacheKey,
    make_cache_key,
    redis_key,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VECTOR_A: list[float] = [0.1, 0.2, 0.3, 0.4, 0.5]
VECTOR_B: list[float] = [0.9, 0.8, 0.7, 0.6, 0.5]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_digest(self) -> None:
        k1 = make_cache_key("github", VECTOR_A, 2000)
        k2 = make_cache_key("github", VECTOR_A, 2000)
        assert k1.hex_digest == k2.hex_digest

    def test_same_inputs_multiple_calls_stable(self) -> None:
        digests = {make_cache_key("confluence", VECTOR_B, 1000).hex_digest for _ in range(10)}
        assert len(digests) == 1

    def test_returns_context_cache_key_type(self) -> None:
        key = make_cache_key("github", VECTOR_A, 2000)
        assert isinstance(key, ContextCacheKey)

    def test_hex_digest_is_16_chars(self) -> None:
        key = make_cache_key("github", VECTOR_A, 2000)
        assert len(key.hex_digest) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", key.hex_digest)


# ---------------------------------------------------------------------------
# Budget sensitivity
# ---------------------------------------------------------------------------


class TestBudgetSensitivity:
    def test_different_budget_different_digest(self) -> None:
        k_low = make_cache_key("github", VECTOR_A, 2000)
        k_high = make_cache_key("github", VECTOR_A, 4000)
        assert k_low.hex_digest != k_high.hex_digest

    def test_budget_zero_is_valid(self) -> None:
        key = make_cache_key("github", VECTOR_A, 0)
        assert len(key.hex_digest) == 16


# ---------------------------------------------------------------------------
# Source sensitivity
# ---------------------------------------------------------------------------


class TestSourceSensitivity:
    def test_different_source_different_key(self) -> None:
        k_github = make_cache_key("github", VECTOR_A, 2000)
        k_confluence = make_cache_key("confluence", VECTOR_A, 2000)
        # source_id field must differ
        assert k_github.source_id != k_confluence.source_id
        # hex_digest is independent of source_id in the hash payload,
        # so digests are equal — but the full cache key (source + digest) is unique
        assert k_github != k_confluence

    def test_source_id_stored_on_key(self) -> None:
        key = make_cache_key("jira", VECTOR_A, 500)
        assert key.source_id == "jira"


# ---------------------------------------------------------------------------
# Float-rounding tolerance
# ---------------------------------------------------------------------------


class TestFloatRoundingTolerance:
    def test_sub_1e7_difference_same_digest(self) -> None:
        """Vectors differing by < 1e-7 in any dimension must collide."""
        vector_base = [0.1000000, 0.2000000, 0.3000000]
        vector_perturbed = [0.1000000 + 5e-8, 0.2000000 - 3e-8, 0.3000000 + 1e-8]
        k1 = make_cache_key("github", vector_base, 1000)
        k2 = make_cache_key("github", vector_perturbed, 1000)
        assert k1.hex_digest == k2.hex_digest

    def test_larger_difference_different_digest(self) -> None:
        """Vectors differing by > 1e-6 must NOT collide."""
        vector_base = [0.100000, 0.200000, 0.300000]
        vector_shifted = [0.100002, 0.200000, 0.300000]  # 2e-6 difference
        k1 = make_cache_key("github", vector_base, 1000)
        k2 = make_cache_key("github", vector_shifted, 1000)
        assert k1.hex_digest != k2.hex_digest

    def test_empty_vector_is_valid(self) -> None:
        key = make_cache_key("github", [], 1000)
        assert len(key.hex_digest) == 16


# ---------------------------------------------------------------------------
# redis_key formatting
# ---------------------------------------------------------------------------


class TestRedisKey:
    def test_pattern_matches_spec(self) -> None:
        key = make_cache_key("github", VECTOR_A, 2000)
        rk = redis_key(key)
        assert re.fullmatch(r"ctx_cache:[^:]+:[0-9a-f]{16}", rk)

    def test_prefix_and_source_id_present(self) -> None:
        key = make_cache_key("confluence", VECTOR_A, 2000)
        rk = redis_key(key)
        assert rk.startswith("ctx_cache:confluence:")

    def test_redis_key_ends_with_hex_digest(self) -> None:
        key = make_cache_key("github", VECTOR_A, 2000)
        rk = redis_key(key)
        assert rk.endswith(key.hex_digest)

    def test_different_sources_different_redis_keys(self) -> None:
        k1 = make_cache_key("github", VECTOR_A, 2000)
        k2 = make_cache_key("jira", VECTOR_A, 2000)
        assert redis_key(k1) != redis_key(k2)
