# TASK-US024-01 — Vault Auth, `JiraConnectorConfig`, and `GrafanaConnectorConfig`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US024-01 |
| User Story | US-024 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define `JiraConnectorConfig` and `GrafanaConnectorConfig` (independently configurable with separate enable/disable toggles — US-024 AC-5), implement `JiraTokenProvider` and `GrafanaTokenProvider` (Vault-backed), and wire `authenticate()` on both connector skeletons. Establishes the credential foundation for TASK-US024-02 and TASK-US024-03.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`, `hvac`

**File locations:**
- `src/connectors/jira/config.py` — `JiraConnectorConfig`
- `src/connectors/jira/auth.py` — `JiraTokenProvider`, `JiraCredential`
- `src/connectors/jira/connector.py` — `JiraConnector` skeleton + `authenticate()`
- `src/connectors/grafana/config.py` — `GrafanaConnectorConfig`
- `src/connectors/grafana/auth.py` — `GrafanaTokenProvider`, `GrafanaCredential`
- `src/connectors/grafana/connector.py` — `GrafanaConnector` skeleton + `authenticate()`
- `tests/connectors/jira/test_jira_auth.py`
- `tests/connectors/grafana/test_grafana_auth.py`

**`JiraConnectorConfig`:**

```python
# src/connectors/jira/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class JiraConnectorConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JIRA_CONNECTOR_", env_file=".env", extra="ignore")

    enabled:          bool  = True
    base_url:         str   = ""   # e.g. "https://acme.atlassian.net"
    email:            str   = ""   # Jira Cloud basic auth email
    default_jql:      str   = 'project in ({projects}) AND status != "Done" ORDER BY updated DESC'
    projects:         list[str] = Field(default_factory=list)   # e.g. ["OPS", "INFRA"]
    max_results:      int   = 50
    default_days:     int   = 30
    vault_path:       str   = "secret/data/jira/token"
    vault_role_id:    str   = ""
    vault_secret_id:  str   = Field(default="", repr=False)
    vault_addr:       str   = "https://vault.internal:8200"
    request_timeout_s: float = 10.0
```

**`GrafanaConnectorConfig`:**

```python
# src/connectors/grafana/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class GrafanaConnectorConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GRAFANA_CONNECTOR_", env_file=".env", extra="ignore")

    enabled:            bool  = True
    base_url:           str   = ""   # e.g. "https://grafana.internal"
    dashboard_uids:     list[str] = Field(default_factory=list)   # scope annotations to specific dashboards
    lookback_hours:     int   = 24   # annotation/alert history window
    max_results:        int   = 100
    vault_path:         str   = "secret/data/grafana/token"
    vault_role_id:      str   = ""
    vault_secret_id:    str   = Field(default="", repr=False)
    vault_addr:         str   = "https://vault.internal:8200"
    request_timeout_s:  float = 10.0
```

**`JiraCredential` and `GrafanaCredential`:**

```python
# src/connectors/jira/auth.py
from pydantic import BaseModel, ConfigDict

class JiraCredential(BaseModel):
    model_config = ConfigDict(frozen=True)
    token: str
    email: str   # combined with token for HTTP Basic auth

# src/connectors/grafana/auth.py
class GrafanaCredential(BaseModel):
    model_config = ConfigDict(frozen=True)
    token: str   # Grafana service account token; used as Bearer
```

**`JiraTokenProvider` and `GrafanaTokenProvider`:**

Both follow the identical pattern established in TASK-US022-01 (`hvac` AppRole login → KV v2 read → return credential model). Only the field names and config types differ:

```python
# src/connectors/jira/auth.py
import asyncio, hvac
from src.connectors.jira.config import JiraConnectorConfig
from src.connector_sdk.exceptions import ConnectorAuthError

class JiraTokenProvider:
    def __init__(self, config: JiraConnectorConfig) -> None:
        self._config = config

    async def get_credential(self) -> JiraCredential:
        try:
            return await asyncio.to_thread(self._read_from_vault)
        except ConnectorAuthError:
            raise
        except Exception as exc:
            raise ConnectorAuthError(f"Jira Vault read failed: {type(exc).__name__}") from exc

    def _read_from_vault(self) -> JiraCredential:
        client = hvac.Client(url=self._config.vault_addr)
        client.auth.approle.login(role_id=self._config.vault_role_id, secret_id=self._config.vault_secret_id)
        data = client.secrets.kv.v2.read_secret_version(
            path=self._config.vault_path, mount_point="secret"
        )["data"]["data"]
        if "token" not in data:
            raise ConnectorAuthError("Vault secret missing 'token' key")
        return JiraCredential(token=data["token"], email=self._config.email)
```

`GrafanaTokenProvider` is identical except it returns `GrafanaCredential(token=data["token"])`.

**Auth header methods:**

```python
# Jira: HTTP Basic (email:token base64) — same scheme as Confluence Cloud
def _auth_headers(self) -> dict[str, str]:
    import base64
    raw   = f"{self._credential.email}:{self._credential.token}"
    token = base64.b64encode(raw.encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}

# Grafana: Bearer service account token
def _auth_headers(self) -> dict[str, str]:
    return {"Authorization": f"Bearer {self._credential.token}", "Accept": "application/json"}
```

**Independent enable/disable (US-024 AC-5):**

`ConnectorRegistry` (TASK-US021-02) loads each connector class independently via entry-point discovery. The `enabled: bool` field in each config is read during `authenticate()`:

```python
async def authenticate(self) -> None:
    if not self._config.enabled:
        raise ConnectorAuthError(f"{self.__class__.__name__} is disabled via config")
    self._credential = await self._token_provider.get_credential()
```

A disabled connector raises `ConnectorAuthError` at auth time; `ConnectorRegistry.load()` marks it `enabled=False` without breaking startup for other connectors.

## Acceptance Criteria

- [ ] `JiraConnector.authenticate()` sets `self._credential` to a `JiraCredential` with `token` and `email`
- [ ] `GrafanaConnector.authenticate()` sets `self._credential` to a `GrafanaCredential` with `token`
- [ ] Jira: `_auth_headers()` returns `Authorization: Basic <base64(email:token)>`
- [ ] Grafana: `_auth_headers()` returns `Authorization: Bearer <token>`
- [ ] `enabled=False` in either config causes `authenticate()` to raise `ConnectorAuthError`
- [ ] Both configs mask `vault_secret_id` in `repr()` (`repr=False`)
- [ ] Vault read failures raise `ConnectorAuthError` (not the raw `hvac` exception)

## Dependencies

- TASK-US021-01 (`BaseConnector`, `ConnectorAuthError`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `hvac.Client` for both connectors; disable-flag path tested
- [ ] `mypy --strict` passes; no `ruff` lint errors
