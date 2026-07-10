# TASK-US022-01 — `GitHubConnectorConfig`, Vault Token Provider, and `authenticate()`

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US022-01 |
| User Story | US-022 |
| Epic | EP-007 — Enterprise Connector Framework |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Define `GitHubConnectorConfig` (connector settings loaded from environment and PostgreSQL), implement `GitHubTokenProvider` (reads a PAT or GitHub App installation token from Vault), and wire `GitHubConnector.authenticate()` to acquire and cache credentials before any API call.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `pydantic-settings`, `hvac` (HashiCorp Vault client)

**File locations:**
- `src/connectors/github/config.py` — `GitHubConnectorConfig`
- `src/connectors/github/auth.py` — `GitHubTokenProvider`, `GitHubCredential`
- `src/connectors/github/connector.py` — `GitHubConnector` class (skeleton + `authenticate()`)
- `tests/connectors/github/test_github_auth.py`

**`GitHubConnectorConfig`:**

```python
# src/connectors/github/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class GitHubConnectorConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix = "GITHUB_CONNECTOR_",
        env_file   = ".env",
        extra      = "ignore",
    )

    repos:            list[str] = Field(
        default_factory=list,
        description="List of 'owner/repo' strings to search. Empty = all accessible repos.",
    )
    default_days:     int   = 30          # commit history window (US-022 AC-4)
    base_url:         str   = "https://api.github.com"
    vault_path:       str   = "secret/data/github/token"   # KV v2 path
    vault_role_id:    str   = ""          # AppRole role_id; injected at deploy time
    vault_secret_id:  str   = ""          # AppRole secret_id; injected at deploy time
    vault_addr:       str   = "https://vault.internal:8200"
    request_timeout_s: float = 10.0
```

**`GitHubCredential`:**

```python
# src/connectors/github/auth.py
from pydantic import BaseModel, ConfigDict

class GitHubCredential(BaseModel):
    model_config = ConfigDict(frozen=True)

    token:      str
    token_type: str   # "pat" | "app_installation"
```

**`GitHubTokenProvider`:**

```python
# src/connectors/github/auth.py
import hvac
from src.connectors.github.config     import GitHubConnectorConfig
from src.connector_sdk.exceptions     import ConnectorAuthError

class GitHubTokenProvider:
    def __init__(self, config: GitHubConnectorConfig) -> None:
        self._config = config

    async def get_credential(self) -> GitHubCredential:
        """
        Read token from Vault KV v2 path.
        Raises ConnectorAuthError on Vault errors or missing secret.
        Never logs token values.
        """
        import asyncio
        try:
            credential = await asyncio.to_thread(self._read_from_vault)
        except Exception as exc:
            raise ConnectorAuthError(
                f"Failed to retrieve GitHub token from Vault: {type(exc).__name__}"
            ) from exc
        return credential

    def _read_from_vault(self) -> GitHubCredential:
        client = hvac.Client(url=self._config.vault_addr)
        client.auth.approle.login(
            role_id   = self._config.vault_role_id,
            secret_id = self._config.vault_secret_id,
        )
        secret = client.secrets.kv.v2.read_secret_version(
            path      = self._config.vault_path,
            mount_point = "secret",
        )
        data = secret["data"]["data"]
        token_type = data.get("token_type", "pat")
        if "token" not in data:
            raise ConnectorAuthError("Vault secret missing 'token' key")
        return GitHubCredential(token=data["token"], token_type=token_type)
```

**`GitHubConnector.authenticate()`:**

```python
# src/connectors/github/connector.py
from src.connector_sdk.base           import BaseConnector
from src.connectors.github.config     import GitHubConnectorConfig
from src.connectors.github.auth       import GitHubTokenProvider, GitHubCredential

class GitHubConnector(BaseConnector):
    def __init__(self, config: GitHubConnectorConfig | None = None) -> None:
        self._config     = config or GitHubConnectorConfig()
        self._token_provider = GitHubTokenProvider(self._config)
        self._credential: GitHubCredential | None = None   # set by authenticate()

    async def authenticate(self) -> None:
        self._credential = await self._token_provider.get_credential()
        # Token is cached in memory; re-called by ConnectorHealthPoller on auth expiry

    def _auth_header(self) -> dict[str, str]:
        if self._credential is None:
            raise ConnectorAuthError("authenticate() has not been called")
        return {"Authorization": f"Bearer {self._credential.token}"}
```

**Security constraints:**
- Token is held in memory only; never written to logs, state, or PostgreSQL
- `vault_secret_id` is never logged — `GitHubConnectorConfig.__repr__` must mask it (Pydantic `repr=False` on field)
- `hvac` calls use `asyncio.to_thread()` — the synchronous Vault SDK must not block the event loop

## Acceptance Criteria

- [ ] `authenticate()` sets `self._credential` to a `GitHubCredential` with `token` non-empty
- [ ] `authenticate()` raises `ConnectorAuthError` when Vault returns a non-200 response (mock)
- [ ] `authenticate()` raises `ConnectorAuthError` when Vault secret is missing the `"token"` key
- [ ] `GitHubConnectorConfig.vault_secret_id` does not appear in `repr(config)`
- [ ] `_auth_header()` raises `ConnectorAuthError` when called before `authenticate()`
- [ ] Vault client is created inside `_read_from_vault()`; not a module-level singleton (avoids stale sessions)

## Dependencies

- TASK-US021-01 (`BaseConnector`, `ConnectorAuthError`)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `hvac.Client` via `unittest.mock.patch`; no live Vault in CI
- [ ] `mypy --strict` passes; no `ruff` lint errors
