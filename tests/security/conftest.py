"""
pytest configuration for the security test suite.

Provides:
  - vault_client  fixture — authenticated hvac.Client
  - k8s           fixture — kubernetes.client.CoreV1Api
  - --run-destructive CLI flag — required to execute @pytest.mark.destructive tests
"""
from __future__ import annotations

import os

import hvac
import pytest
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config


# ──────────────────────────────────────────────────────────────────────────────
# Destructive test gating
# ──────────────────────────────────────────────────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "destructive: marks tests that delete or modify live cluster resources "
        "(skipped unless --run-destructive is passed)",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-destructive",
        action="store_true",
        default=False,
        help="Include @pytest.mark.destructive tests (e.g. HA failover pod deletion). "
             "DO NOT use in shared dev clusters.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if not config.getoption("--run-destructive"):
        skip_destructive = pytest.mark.skip(
            reason="Skipped: pass --run-destructive to execute HA failover tests"
        )
        for item in items:
            if item.get_closest_marker("destructive"):
                item.add_marker(skip_destructive)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def vault_client() -> hvac.Client:
    """Authenticated hvac client for Vault integration assertions."""
    vault_addr = os.environ.get(
        "VAULT_ADDR",
        "https://vault.contextiq-security.svc.cluster.local:8200",
    )
    # VAULT_TOKEN is injected by CI secrets — never committed to the repository
    vault_token = os.environ["VAULT_TOKEN"]
    client = hvac.Client(url=vault_addr, token=vault_token, verify=False)
    assert client.is_authenticated(), "Vault test client is not authenticated"
    return client


@pytest.fixture(scope="session")
def k8s() -> k8s_client.CoreV1Api:
    """Kubernetes API client — in-cluster config in CI, ~/.kube/config locally."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return k8s_client.CoreV1Api()
