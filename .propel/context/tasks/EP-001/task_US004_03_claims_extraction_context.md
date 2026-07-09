# TASK-US004-03 — JWT Claims Extraction and RequestContext Population

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US004-03 |
| User Story | US-004 |
| Epic | EP-001 — Enterprise MCP Gateway |
| Layer | Backend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Extract the verified JWT claims (`sub`, `roles`, `email`, `preferred_username`) and populate the `RequestContext` (established in TASK-US003-04) so that downstream RBAC checks, audit logging, and execution traces all have access to the authenticated identity without re-reading the token.

## Implementation Details

**Technology:** Python 3.11+, Pydantic v2, `contextvars`

**File locations:**
- `src/gateway/schemas/auth_types.py` — `JWTClaims` Pydantic model
- `src/gateway/context/request_context.py` — `RequestContext` extended with auth fields
- `src/gateway/middleware/jwt_auth.py` — claims-to-context binding (extends TASK-US004-01)
- `tests/gateway/test_claims_extraction.py`

**`JWTClaims` model:**
```python
class JWTClaims(BaseModel):
    sub: str                        # Keycloak user UUID
    preferred_username: str
    email: EmailStr | None = None
    realm_access: dict = {}         # {"roles": ["DEVELOPER", "PLATFORM_ENGINEER"]}
    resource_access: dict = {}      # per-client roles
    exp: int
    iat: int
    iss: str

    @property
    def roles(self) -> set[str]:
        return set(self.realm_access.get("roles", []))
```

**Role extraction from Keycloak token structure:**
Keycloak embeds roles in `realm_access.roles` (realm-level) and `resource_access.<client-id>.roles` (client-level). Merge both sources:
```python
@property
def roles(self) -> set[str]:
    realm_roles = set(self.realm_access.get("roles", []))
    client_roles = set(
        self.resource_access
            .get(settings.keycloak_client_id, {})
            .get("roles", [])
    )
    return realm_roles | client_roles
```

**Extend `RequestContext` with auth fields:**
```python
@dataclass(frozen=True)
class RequestContext:
    request_id: str
    user_id: str          # = claims.sub
    username: str         # = claims.preferred_username
    roles: frozenset[str] # = frozenset(claims.roles)
    session_id: str
    trace_id: int
```

**Middleware binding** (after `JWKSClient.verify()` succeeds in TASK-US004-01):
```python
ctx = RequestContext(
    request_id=str(uuid4()),
    user_id=claims.sub,
    username=claims.preferred_username,
    roles=frozenset(claims.roles),
    session_id=_derive_session_id(scope),
    trace_id=trace.get_current_span().get_span_context().trace_id,
)
set_request_context(ctx)
```

**Known roles whitelist validation:** On context creation, log a WARNING if the token contains roles not in the platform's known set (`DEVELOPER`, `PLATFORM_ENGINEER`, `DEVOPS_SRE`, `ADMIN`, `SECURITY_OFFICER`, `MANAGER`, `AUDITOR`). Do not reject — unknown roles are simply not granted any permissions.

## Acceptance Criteria

- [ ] `RequestContext.user_id` equals the JWT `sub` claim for every authenticated request
- [ ] `RequestContext.roles` is a `frozenset` combining both `realm_access.roles` and `resource_access.<client>.roles`
- [ ] Downstream handlers access user identity via `get_request_context()` with no re-parsing of the JWT
- [ ] `RequestContext` is immutable (`frozen=True`) — no handler can modify the auth context mid-request
- [ ] Token with no roles results in `roles = frozenset()` (not an error; RBAC guards deny access per missing permission)
- [ ] Unknown roles emit a `WARNING` log entry and are silently ignored (not rejected)
- [ ] Unit tests cover: role merging from both claim paths, empty roles, unknown roles, `frozenset` immutability

## Dependencies

- TASK-US004-01 (middleware sets context after verify)
- TASK-US004-02 (`JWTClaims` returned by `verify()`)
- TASK-US003-04 (`RequestContext` and `ContextVar` infrastructure)

## Definition of Done

- [ ] `RequestContext.roles` used by RBAC guard in TASK-US002-02 (`POST /v1/tools` requires `ADMIN`)
- [ ] Unit coverage ≥ 90% for `schemas/auth_types.py` role-extraction logic
- [ ] `KEYCLOAK_CLIENT_ID` env var documented and used for `resource_access` role extraction
- [ ] `mypy --strict` passes on all `auth_types.py` and `request_context.py` changes
