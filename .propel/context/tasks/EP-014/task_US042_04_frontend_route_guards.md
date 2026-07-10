# TASK-US042-04 — React Admin Portal Route Guards Per Role

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US042-04 |
| User Story | US-042 |
| Epic | EP-014 — Enterprise RBAC & Authentication |
| Layer | Frontend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Replace the bespoke `RequireAdmin` and `RequireSecurityOfficer` guards in the Admin Portal SPA (US-039, US-040) with a single generic `RequireRoles` guard. Wire each Admin Portal route to the correct role set drawn from the same permission matrix applied on the backend (AC-1, AC-2). Unauthenticated users are redirected to `/login`; authenticated users without the required role are redirected to `/403`.

## Implementation Details

**Technology:** React 18, TypeScript, React Router v6, `src/context/AuthContext.tsx`

**File locations:**
- `frontend/admin-portal/src/guards/RequireRoles.tsx` — generic role guard (replaces `RequireAdmin` and `RequireSecurityOfficer`)
- `frontend/admin-portal/src/guards/index.ts` — re-export
- `frontend/admin-portal/src/routes/index.tsx` — extend with correct guard per route
- `frontend/admin-portal/src/pages/errors/ForbiddenPage.tsx` — 403 page
- `frontend/admin-portal/src/pages/errors/LoginPage.tsx` — login redirect stub

---

### Role constants mirroring backend `PlatformRole`

```ts
// frontend/admin-portal/src/auth/roles.ts
/**
 * Mirror of src/auth/roles.py PlatformRole values.
 * Kept in sync with backend — if a role is renamed there, update here too.
 */
export const PlatformRole = {
  DEVELOPER:         "developer",
  PLATFORM_ENGINEER: "platform_engineer",
  DEVOPS_SRE:        "devops_sre",
  ADMIN:             "admin",
  SECURITY_OFFICER:  "security_officer",
  MANAGER:           "manager",
  AUDITOR:           "auditor",
} as const;

export type PlatformRoleValue = typeof PlatformRole[keyof typeof PlatformRole];

/** Returns true if userRoles contains at least one of allowedRoles (case-insensitive). */
export function hasAnyRole(
  userRoles:    string[],
  allowedRoles: PlatformRoleValue[],
): boolean {
  const normalised = userRoles.map((r) => r.toLowerCase());
  // ADMIN always passes
  if (normalised.includes(PlatformRole.ADMIN)) return true;
  return allowedRoles.some((r) => normalised.includes(r.toLowerCase()));
}
```

---

### `RequireRoles` generic guard

```tsx
// frontend/admin-portal/src/guards/RequireRoles.tsx
import { Navigate }          from "react-router-dom";
import { useAuth }           from "../context/AuthContext";
import { hasAnyRole }        from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import type { ReactNode }    from "react";

interface Props {
  /** Roles that are allowed to see the wrapped content. ADMIN always passes. */
  allowedRoles: PlatformRoleValue[];
  children:     ReactNode;
}

/**
 * AC-1 / AC-2: Redirects to /login if not authenticated,
 * to /403 if authenticated but missing required role.
 */
export function RequireRoles({ allowedRoles, children }: Props) {
  const { user } = useAuth();

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (!hasAnyRole(user.roles, allowedRoles)) {
    return <Navigate to="/403" replace />;
  }

  return <>{children}</>;
}
```

---

### `guards/index.ts` — convenience re-exports

```ts
// frontend/admin-portal/src/guards/index.ts
export { RequireRoles } from "./RequireRoles";

import { PlatformRole } from "../auth/roles";
import { RequireRoles } from "./RequireRoles";
import type { ReactNode } from "react";

// Named guards for common permission groups (match backend named callables)
export const RequireAdmin = ({ children }: { children: ReactNode }) =>
  <RequireRoles allowedRoles={[PlatformRole.ADMIN]}>{children}</RequireRoles>;

export const RequirePlatformEngineer = ({ children }: { children: ReactNode }) =>
  <RequireRoles allowedRoles={[PlatformRole.PLATFORM_ENGINEER, PlatformRole.ADMIN]}>{children}</RequireRoles>;

export const RequireSecurityOfficer = ({ children }: { children: ReactNode }) =>
  <RequireRoles allowedRoles={[PlatformRole.SECURITY_OFFICER, PlatformRole.ADMIN]}>{children}</RequireRoles>;

export const RequireAuditor = ({ children }: { children: ReactNode }) =>
  <RequireRoles allowedRoles={[
    PlatformRole.AUDITOR,
    PlatformRole.DEVOPS_SRE,
    PlatformRole.SECURITY_OFFICER,
    PlatformRole.ADMIN,
  ]}>{children}</RequireRoles>;

export const RequireManager = ({ children }: { children: ReactNode }) =>
  <RequireRoles allowedRoles={[
    PlatformRole.MANAGER,
    PlatformRole.PLATFORM_ENGINEER,
    PlatformRole.ADMIN,
  ]}>{children}</RequireRoles>;
```

---

### Updated `ADMIN_ROUTES` with correct per-route guards

```tsx
// frontend/admin-portal/src/routes/index.tsx  (replace guard wrappers)
import {
  RequireRoles, RequirePlatformEngineer,
  RequireSecurityOfficer, RequireAuditor, RequireManager,
} from "../guards";
import { PlatformRole } from "../auth/roles";

export const ADMIN_ROUTES: RouteObject[] = [
  {
    path:    "/",
    element: (
      // Root requires any authenticated user with at least one valid role
      <RequireRoles allowedRoles={[
        PlatformRole.DEVELOPER, PlatformRole.PLATFORM_ENGINEER,
        PlatformRole.DEVOPS_SRE, PlatformRole.ADMIN,
        PlatformRole.SECURITY_OFFICER, PlatformRole.MANAGER, PlatformRole.AUDITOR,
      ]}>
        <AdminLayout />
      </RequireRoles>
    ),
    children: [
      // Connectors — PLATFORM_ENGINEER or ADMIN
      {
        path:    "connectors",
        element: <RequirePlatformEngineer><ConnectorListPage /></RequirePlatformEngineer>,
      },
      {
        path:    "connectors/add",
        element: <RequirePlatformEngineer><AddConnectorPage /></RequirePlatformEngineer>,
      },

      // Policies — SECURITY_OFFICER or ADMIN
      {
        path:    "policies",
        element: <RequireSecurityOfficer><PolicyListPage /></RequireSecurityOfficer>,
      },
      {
        path:    "policies/:id",
        element: <RequireSecurityOfficer><PolicyDetailPage /></RequireSecurityOfficer>,
      },
      {
        path:    "policies/new",
        element: <RequireSecurityOfficer><PolicyDetailPage /></RequireSecurityOfficer>,
      },

      // Models — PLATFORM_ENGINEER or ADMIN
      {
        path:    "models",
        element: <RequirePlatformEngineer><ModelListPage /></RequirePlatformEngineer>,
      },
      {
        path:    "models/add",
        element: <RequirePlatformEngineer><AddModelPage /></RequirePlatformEngineer>,
      },
      {
        path:    "models/weights",
        element: <RequirePlatformEngineer><RoutingWeightsPage /></RequirePlatformEngineer>,
      },

      // Traces / Replay — AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN
      {
        path:    "traces",
        element: <RequireAuditor><ReplayExplorerPage /></RequireAuditor>,
      },
      {
        path:    "traces/:id",
        element: <RequireAuditor><TraceDetailPage /></RequireAuditor>,
      },

      // Cost analytics — MANAGER, PLATFORM_ENGINEER, or ADMIN
      // (accessed via the ModelListPage tab — no dedicated route needed)

      // Error pages — no role guard
      { path: "403", element: <ForbiddenPage /> },
      { path: "login", element: <LoginPage /> },
    ],
  },
];
```

---

### `ForbiddenPage` — 403 UI

```tsx
// frontend/admin-portal/src/pages/errors/ForbiddenPage.tsx
import { Link } from "react-router-dom";

export function ForbiddenPage() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen gap-4"
          aria-labelledby="forbidden-heading">
      <h1 id="forbidden-heading" className="text-3xl font-bold text-gray-800">
        403 — Access Denied
      </h1>
      <p className="text-gray-500 text-sm">
        You do not have the role required to view this page.
        Contact your administrator to request access.
      </p>
      <Link to="/" className="btn-secondary text-sm" aria-label="Go to home page">
        Go Home
      </Link>
    </main>
  );
}
```

---

### `AuthContext` — expose `hasRole` helper

```tsx
// frontend/admin-portal/src/context/AuthContext.tsx  (extend)
import { hasAnyRole, type PlatformRoleValue } from "../auth/roles";

// Add to AuthContextValue interface:
interface AuthContextValue {
  // ...existing fields...
  hasRole:  (role: PlatformRoleValue) => boolean;
  hasAnyRole: (roles: PlatformRoleValue[]) => boolean;
}

// Add to AuthProvider value:
hasRole:    (role) => hasAnyRole(user?.roles ?? [], [role]),
hasAnyRole: (roles) => hasAnyRole(user?.roles ?? [], roles),
```

## Acceptance Criteria

- [ ] `RequireRoles({ allowedRoles: ["auditor"] })` redirects to `/403` for a user with only `DEVELOPER` role (AC-1)
- [ ] `RequireRoles` with any list redirects to `/login` when `user` is `null` (unauthenticated)
- [ ] `ADMIN` role passes every `RequireRoles` check regardless of `allowedRoles` list (ADMIN super-role — AC-1)
- [ ] Role comparison is case-insensitive — `"SECURITY_OFFICER"` and `"security_officer"` both grant access to `RequireSecurityOfficer` (AC-4)
- [ ] `/connectors`, `/models`, and `/models/weights` render only for `PLATFORM_ENGINEER` or `ADMIN` users (AC-2)
- [ ] `/policies` and `/policies/:id` render only for `SECURITY_OFFICER` or `ADMIN` users (AC-2)
- [ ] `/traces` and `/traces/:id` render only for `AUDITOR`, `DEVOPS_SRE`, `SECURITY_OFFICER`, or `ADMIN` (AC-2)
- [ ] `ForbiddenPage` has `aria-labelledby` referencing the `<h1>` (WCAG 2.1 AA)

## Dependencies

- TASK-US039-01 — `ADMIN_ROUTES`, `AuthContext`
- TASK-US040-01 — replaces the local `RequireSecurityOfficer` implemented there
- TASK-US042-01 — `PlatformRole` values; `roles.ts` mirrors the Python enum

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] React Testing Library tests: guard redirects to /403, guard redirects to /login, ADMIN passes all guards
