# TASK-US025-02 — `VaultPathValidator`: Pre-Creation Vault Path Verification

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US025-02 |
| User Story | US-025 |
| Epic | EP-008 — Knowledge Source Management & Indexing |
| Layer | Backend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `VaultPathValidator` — a component called during knowledge source creation that verifies the supplied `credentials_vault_path` actually exists in Vault before the record is written to PostgreSQL. An unreachable or non-existent path returns a descriptive `HTTP 400` error at creation time (US-025 AC-5), preventing sources that can never authenticate from entering the system.

## Implementation Details

**Technology:** Python 3.11+, `hvac`, `pydantic-settings`

**File locations:**
- `src/knowledge_sources/vault_validator.py` — `VaultPathValidator`, `VaultValidationResult`
- `src/knowledge_sources/config.py` — `KnowledgeSourceSettings`
- `tests/knowledge_sources/test_vault_validator.py`

**`KnowledgeSourceSettings`:**

```python
# src/knowledge_sources/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class KnowledgeSourceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KNOWLEDGE_SOURCE_", env_file=".env", extra="ignore")

    vault_addr:      str  = "https://vault.internal:8200"
    vault_role_id:   str  = ""
    vault_secret_id: str  = ""
    vault_mount:     str  = "secret"   # KV v2 mount name
```

**`VaultValidationResult`:**

```python
# src/knowledge_sources/vault_validator.py
from pydantic import BaseModel, ConfigDict

class VaultValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid:   bool
    message: str   # human-readable; surfaced directly in HTTP 400 response detail
```

**`VaultPathValidator`:**

```python
# src/knowledge_sources/vault_validator.py
import asyncio, hvac
from src.knowledge_sources.config import KnowledgeSourceSettings

class VaultPathValidator:
    def __init__(self, settings: KnowledgeSourceSettings | None = None) -> None:
        self._settings = settings or KnowledgeSourceSettings()

    async def validate(self, vault_path: str) -> VaultValidationResult:
        """
        Attempt to read the Vault secret metadata at `vault_path`.
        Returns VaultValidationResult(valid=True) on success.
        Returns VaultValidationResult(valid=False, message=...) on any failure.
        Never raises — all exceptions are caught and reported.
        """
        try:
            return await asyncio.to_thread(self._check_vault, vault_path)
        except Exception as exc:
            return VaultValidationResult(
                valid   = False,
                message = f"Vault validation error: {type(exc).__name__}: {str(exc)[:200]}",
            )

    def _check_vault(self, vault_path: str) -> VaultValidationResult:
        client = hvac.Client(url=self._settings.vault_addr)
        try:
            client.auth.approle.login(
                role_id   = self._settings.vault_role_id,
                secret_id = self._settings.vault_secret_id,
            )
        except Exception as exc:
            return VaultValidationResult(
                valid   = False,
                message = f"Vault authentication failed — check platform Vault credentials: {type(exc).__name__}",
            )

        try:
            # Read metadata only (not the secret value) to confirm the path exists
            client.secrets.kv.v2.read_secret_metadata(
                path        = vault_path,
                mount_point = self._settings.vault_mount,
            )
            return VaultValidationResult(valid=True, message="Vault path exists")
        except hvac.exceptions.InvalidPath:
            return VaultValidationResult(
                valid   = False,
                message = f"Vault path '{vault_path}' does not exist in mount '{self._settings.vault_mount}'",
            )
        except hvac.exceptions.Forbidden:
            return VaultValidationResult(
                valid   = False,
                message = f"Vault path '{vault_path}' exists but platform role lacks read permission",
            )
        except Exception as exc:
            return VaultValidationResult(
                valid   = False,
                message = f"Vault path check failed: {type(exc).__name__}: {str(exc)[:200]}",
            )
```

**Why `read_secret_metadata` not `read_secret_version`:**

Reading metadata (`/metadata/{path}`) does not count as a secret access in Vault audit logs and does not consume the secret's `max_uses`. It is the lightest-weight probe that confirms the path exists and the platform role has read permission, without retrieving the actual token value at creation time.

**Error message specificity:**

| Failure | `message` example |
|---|---|
| Path does not exist | `"Vault path 'secret/data/my/token' does not exist in mount 'secret'"` |
| Permission denied | `"Vault path '...' exists but platform role lacks read permission"` |
| Vault unreachable | `"Vault authentication failed — check platform Vault credentials: ConnectionError"` |

The caller (`KnowledgeSourceService`) translates `valid=False` to an `HTTP 400` with `detail=result.message`.

## Acceptance Criteria

- [ ] `validate()` returns `VaultValidationResult(valid=True)` for a path that exists in mocked Vault
- [ ] `validate()` returns `valid=False` with a descriptive message when `InvalidPath` is raised
- [ ] `validate()` returns `valid=False` with a descriptive message when `Forbidden` is raised
- [ ] `validate()` returns `valid=False` when Vault AppRole login fails
- [ ] `validate()` never raises — all exceptions are caught and reflected in `message`
- [ ] `validate()` uses `read_secret_metadata` (not `read_secret_version`) — verified by mock assertion

## Dependencies

- TASK-US025-01 (`KnowledgeSourceCreate.credentials_vault_path` — the value being validated)

## Definition of Done

- [ ] Code reviewed and merged to `main`
- [ ] Tests mock `hvac.Client`; all 5 failure branches covered
- [ ] `mypy --strict` passes; no `ruff` lint errors
