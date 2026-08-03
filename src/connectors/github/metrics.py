"""
Prometheus metrics for the GitHub connector.

TASK-US022-02: GitHubSearchClient — Code Search API with Exponential Backoff.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

github_rate_limit_hits_total = Counter(
    "github_rate_limit_hits_total",
    "Number of GitHub API 429 rate-limit responses encountered",
    ["endpoint"],
)

github_search_latency_seconds = Histogram(
    "github_search_latency_seconds",
    "End-to-end latency of GitHub code search requests",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)
