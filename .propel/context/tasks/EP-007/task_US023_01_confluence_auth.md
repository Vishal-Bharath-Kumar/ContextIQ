# TASK-US023-01 — `ConfluenceConnectorConfig`, Vault Token Provider, and `authenticate()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US023-01 |
| User Story | US-023 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define `ConfluenceConnectorConfig` (deployment-aware settings supporting both Cloud and Data Center), implement `ConfluenceTokenProvider` (reads an API token from Vault), and wire `ConfluenceConnector.authenticate()` to acquire and cache credentials. Satisfies US-023 AC-1 and AC-4 (configurable base URL for Cloud vs. Data Center).

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`, `hvac`

**File locations:**
- `src/connectors/confluence/config.py` — `ConfluenceConnectorConfig`, `ConfluenceDeploymentType`
- `src/connectors/confluence/auth.py` — `ConfluenceTokenProvider`, `ConfluenceCredential`
- `src/connectors/confluence/connector.py` — `ConfluenceConnector` skeleton + `authenticate()`
- `tests/connectors/confluence/test_confluence_auth.py`

**`ConfluenceDeploymentType` and `ConfluenceConnectorConfig`:**

```python
# src/connectors/confluence/config.py
from enum import StrEnum
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class ConfluenceDeploymentType(StrEnum):
    CLOUD      = "cloud"       # Confluence Cloud — auth via basic auth (email + API token)
    DATACENTER = "datacenter"  # Confluence Data Center / Server — auth via PAT (Bearer)

class ConfluenceConnectorConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix = "CONFLUENCE_CONNECTOR_",
        env_file   = ".env",
        extra      = "ignore",
    )

    base_url:         str                    # e.g. "https://acme.atlassian.net" or "https://confluence.internal"
    deployment_type:  ConfluenceDeploymentType = ConfluenceDeploymentType.CLOUD
    spaces:           list[str]              = Field(default_factory=list)  # e.g. ["~ENG", "ARCH"]
    email:            str                    = ""   # Cloud only: user email for basic auth
    vault_path:       str                    = "secret/data/confluence/token"
    vault_role_id:    str                    = ""
    vault_secret_id:  str                    = Field(default="", repr=False)  # masked in repr
    vault_addr:       str                    = "https://vault.internal:8200"
    request_timeout_s: float                 = 10.0
    default_days:     int                    = 30   # lookback window for first sync
```

**`ConfluenceCredential`:**

```python
# src/connectors/confluence/auth.py
from pydantic import BaseModel, ConfigDict
from src.connectors.confluence.config import ConfluenceDeploymentType

class ConfluenceCredential(BaseModel):
    model_config = ConfigDict(frozen=True)

    token:           str
    deployment_type: ConfluenceDeploymentType
    email:           str = ""   # populated for Cloud; empty for Data Center
```

**`ConfluenceTokenProvider`:**

```python
# src/connectors/confluence/auth.py
import asyncio
import hvac
from src.connectors.confluence.config import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connector_sdk.exceptions      import ConnectorAuthError

class ConfluenceTokenProvider:
    def __init__(self, config: ConfluenceConnectorConfig) -> None:
        self._config = config

    async def get_credential(self) -> ConfluenceCredential:
        try:
            return await asyncio.to_thread(self._read_from_vault)
        except ConnectorAuthError:
            raise
        except Exception as exc:
            raise ConnectorAuthError(
                f"Failed to retrieve Confluence token from Vault: {type(exc).__name__}"
            ) from exc

    def _read_from_vault(self) -> ConfluenceCredential:
        client = hvac.Client(url=self._config.vault_addr)
        client.auth.approle.login(
            role_id   = self._config.vault_role_id,
            secret_id = self._config.vault_secret_id,
        )
        secret = client.secrets.kv.v2.read_secret_version(
            path        = self._config.vault_path,
            mount_point = "secret",
        )
        data = secret["data"]["data"]
        if "token" not in data:
            raise ConnectorAuthError("Vault secret missing 'token' key")
        return ConfluenceCredential(
            token           = data["token"],
            deployment_type = self._config.deployment_type,
            email           = self._config.email,
        )
```

**`ConfluenceConnector.authenticate()` + `_auth_headers()`:**

```python
# src/connectors/confluence/connector.py
import base64
from src.connector_sdk.base             import BaseConnector
from src.connector_sdk.exceptions       import ConnectorAuthError
from src.connectors.confluence.config   import ConfluenceConnectorConfig, ConfluenceDeploymentType
from src.connectors.confluence.auth     import ConfluenceTokenProvider, ConfluenceCredential

class ConfluenceConnector(BaseConnector):
    def __init__(self, config: ConfluenceConnectorConfig | None = None) -> None:
        self._config          = config or ConfluenceConnectorConfig()
        self._token_provider  = ConfluenceTokenProvider(self._config)
        self._credential: ConfluenceCredential | None = None

    async def authenticate(self) -> None:
        self._credential = await self._token_provider.get_credential()

    def _auth_headers(self) -> dict[str, str]:
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        if self._credential.deployment_type == ConfluenceDeploymentType.CLOUD:
            # Cloud: Basic auth with email:token (base64-encoded)
            raw   = f"{self._credential.email}:{self._credential.token}"
            token = base64.b64encode(raw.encode()).decode()
            return {"Authorization": f"Basic {token}", "Accept": "application/json"}
        else:
            # Data Center: Bearer token (PAT)
            return {"Authorization": f"Bearer {self._credential.token}", "Accept": "application/json"}
```

**Auth scheme differences:**

| Deployment | Auth method | Header |
|---|---|---|
| Cloud | HTTP Basic (email:api_token, base64) | `Authorization: Basic <b64>` |
| Data Center | Bearer PAT | `Authorization: Bearer <token>` |

Both schemes are handled entirely in `_auth_headers()`; no auth logic leaks into the search or sync clients.

## Acceptance Criteria

- [ ] `authenticate()` sets `self._credential` to a `ConfluenceCredential` (Cloud and Data Center paths)
- [ ] Cloud: `_auth_headers()` returns `Authorization: Basic <base64(email:token)>`
- [ ] Data Center: `_auth_headers()` returns `Authorization: Bearer <token>`
- [ ] `authenticate()` raises `ConnectorAuthError` when Vault returns a non-200 response
- [ ] `authenticate()` raises `ConnectorAuthError` when Vault secret is missing the `"token"` key
- [ ] `ConfluenceConnectorConfig.vault_secret_id` does not appear in `repr(config)` (`repr=False`)
- [ ] `_auth_headers()` raises `ConnectorAuthError` when called before `authenticate()`

## Dependencies

- TASK-US021-01 (`BaseConnector`, `ConnectorAuthError`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `hvac.Client`; both Cloud and Data Center auth paths covered
- [ ] `mypy --strict` passes; no `ruff` lint errors
