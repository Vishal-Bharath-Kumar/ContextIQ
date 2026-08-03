# TASK-US040-01 — Policy List Page and `SECURITY_OFFICER` / `ADMIN` Route Guard

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US040-01 |
| User Story | US-040 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the policy list page (AC-1) that renders all governance policies with their version history, active version badge, author, and activation timestamp. Add a `RequireSecurityOfficer` route guard (AC-7) that allows access only to users with the `SECURITY_OFFICER` or `ADMIN` role from their JWT claims. Register the policy routes in the Admin Portal's shared `ADMIN_ROUTES` (established in TASK-US039-01). A `GET /v1/policies` backend route is also added here since the US-033 tasks only defined mutating routes.

## Implementation Details

**Technology:** React 18, TypeScript, TanStack Query v5, React Router v6 (lazy route), date-fns, Tailwind CSS, Radix UI Badge

**File locations:**
- `frontend/admin-portal/src/guards/RequireSecurityOfficer.tsx`
- `frontend/admin-portal/src/pages/policies/PolicyListPage.tsx`
- `frontend/admin-portal/src/components/policies/PolicyVersionRow.tsx`
- `frontend/admin-portal/src/components/policies/PolicyActiveBadge.tsx`
- `frontend/admin-portal/src/services/policyService.ts`
- `frontend/admin-portal/src/routes/index.tsx` — extend with policy routes
- `src/api/admin/routes/policies.py` — add `GET /v1/policies` list route (backend extension)

---

### Backend: `GET /v1/policies` list route

```python
# src/api/admin/routes/policies.py  (extend existing router — add list route)
from src.governance.policy.schemas import PolicyVersion, PolicyRecord

class PolicyListItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id:             uuid.UUID
    name:           str
    active_version: str | None     # version string of the currently active version, if any
    versions:       list[PolicyVersion]  # all versions, newest first
    latest_author:  str
    activated_at:   datetime | None


@router.get(
    "",
    response_model = list[PolicyListItem],
    summary        = "List all governance policies with their full version history (AC-1).",
)
async def list_policies(
    claims:  AdminClaims,
    session: AsyncSession = Depends(get_async_session),
) -> list[PolicyListItem]:
    repo  = PolicyRepository(session)
    items = await repo.list_all_with_versions()   # returns grouped by policy name
    return items
```

---

### `PolicyListItem` TypeScript interface

```ts
// frontend/admin-portal/src/services/policyService.ts
import axios                         from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface PolicyVersion {
  id:           string;
  name:         string;
  version:      string;
  status:       "draft" | "active" | "superseded" | "rolled_back";
  author:       string;
  description:  string;
  activated_at: string | null;   // ISO-8601
  created_at:   string;
}

export interface PolicyListItem {
  id:             string;
  name:           string;
  active_version: string | null;
  versions:       PolicyVersion[];
  latest_author:  string;
  activated_at:   string | null;
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api" });
api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) cfg.headers.Authorization = `Bearer ${JSON.parse(raw).token}`;
  return cfg;
});

export const POLICY_KEYS = {
  all:    ["policies"]                  as const,
  detail: (id: string) => ["policies", id] as const,
};

export function usePolicies() {
  return useQuery({
    queryKey: POLICY_KEYS.all,
    queryFn:  () =>
      api.get<PolicyListItem[]>("/v1/policies").then((r) => r.data),
  });
}

export function useCreatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; description: string; version: string; rego_body: string }) =>
      api.post<PolicyVersion>("/v1/policies", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: POLICY_KEYS.all }),
  });
}
```

---

### `RequireSecurityOfficer` route guard

```tsx
// frontend/admin-portal/src/guards/RequireSecurityOfficer.tsx
import { Navigate } from "react-router-dom";
import { useAuth }  from "../context/AuthContext";
import type { ReactNode } from "react";

interface Props { children: ReactNode; }

/**
 * AC-7: Allows access only to users with SECURITY_OFFICER or ADMIN role.
 * Redirects to /403 for all other authenticated users.
 */
export function RequireSecurityOfficer({ children }: Props) {
  const { user } = useAuth();

  if (!user) return <Navigate to="/login" replace />;

  const roles = user.roles.map((r) => r.toLowerCase());
  const hasAccess = roles.includes("security_officer") || roles.includes("admin");

  if (!hasAccess) return <Navigate to="/403" replace />;

  return <>{children}</>;
}
```

---

### Route registration

```tsx
// frontend/admin-portal/src/routes/index.tsx  (extend ADMIN_ROUTES — add policy entries)
const PolicyListPage   = lazy(() => import("../pages/policies/PolicyListPage"));
const PolicyDetailPage = lazy(() => import("../pages/policies/PolicyDetailPage"));  // TASK-US040-02

// Add inside the children array of the root route:
{ path: "policies",        element: <RequireSecurityOfficer><PolicyListPage /></RequireSecurityOfficer> },
{ path: "policies/:id",    element: <RequireSecurityOfficer><PolicyDetailPage /></RequireSecurityOfficer> },
{ path: "policies/new",    element: <RequireSecurityOfficer><PolicyDetailPage /></RequireSecurityOfficer> },
```

---

### `PolicyListPage`

```tsx
// frontend/admin-portal/src/pages/policies/PolicyListPage.tsx
import { Link }              from "react-router-dom";
import { usePolicies }       from "../../services/policyService";
import { PolicyVersionRow }  from "../../components/policies/PolicyVersionRow";

export default function PolicyListPage() {
  const { data: policies, isLoading, isError } = usePolicies();

  return (
    <main aria-labelledby="policies-heading">
      <div className="flex items-center justify-between mb-6">
        <h1 id="policies-heading" className="text-2xl font-semibold">
          Governance Policies
        </h1>
        <Link to="/policies/new" className="btn-primary" aria-label="Create new policy">
          New Policy
        </Link>
      </div>

      {isLoading && <p role="status" aria-live="polite">Loading policies…</p>}
      {isError   && <p role="alert">Failed to load policies. Please retry.</p>}

      {policies?.map((policy) => (
        <section
          key={policy.id}
          aria-labelledby={`policy-${policy.id}-name`}
          className="mb-8 border rounded-lg overflow-hidden"
        >
          <div className="flex items-center gap-3 px-4 py-3 bg-gray-50 border-b">
            <h2 id={`policy-${policy.id}-name`} className="text-base font-semibold">
              {policy.name}
            </h2>
            {policy.active_version && (
              <PolicyActiveBadge version={policy.active_version} />
            )}
          </div>

          <table className="w-full text-sm" aria-label={`Version history for ${policy.name}`}>
            <thead>
              <tr className="text-left text-gray-500 text-xs uppercase bg-gray-50">
                <th scope="col" className="px-4 py-2">Version</th>
                <th scope="col" className="px-4 py-2">Status</th>
                <th scope="col" className="px-4 py-2">Author</th>
                <th scope="col" className="px-4 py-2">Activated</th>
                <th scope="col" className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {policy.versions.map((v) => (
                <PolicyVersionRow key={v.id} version={v} policyId={policy.id} />
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </main>
  );
}
```

---

### `PolicyActiveBadge` and `PolicyVersionRow`

```tsx
// frontend/admin-portal/src/components/policies/PolicyActiveBadge.tsx
interface Props { version: string; }

export function PolicyActiveBadge({ version }: Props) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800"
      aria-label={`Active version: ${version}`}
    >
      Active v{version}
    </span>
  );
}
```

```tsx
// frontend/admin-portal/src/components/policies/PolicyVersionRow.tsx
import { formatDistanceToNow } from "date-fns";
import { Link }               from "react-router-dom";
import type { PolicyVersion } from "../../services/policyService";

const STATUS_CLASS: Record<PolicyVersion["status"], string> = {
  active:      "text-green-700 font-medium",
  draft:       "text-blue-600",
  superseded:  "text-gray-400",
  rolled_back: "text-orange-600",
};

interface Props { version: PolicyVersion; policyId: string; }

export function PolicyVersionRow({ version, policyId }: Props) {
  const activatedAt = version.activated_at
    ? formatDistanceToNow(new Date(version.activated_at), { addSuffix: true })
    : "—";

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="px-4 py-2">{version.version}</td>
      <td className={`px-4 py-2 capitalize ${STATUS_CLASS[version.status]}`}>
        {version.status}
      </td>
      <td className="px-4 py-2 text-gray-500">{version.author}</td>
      <td className="px-4 py-2 text-gray-500">{activatedAt}</td>
      <td className="px-4 py-2">
        <Link
          to={`/policies/${policyId}?version=${version.version}`}
          className="text-blue-600 hover:underline text-xs"
          aria-label={`Edit policy ${version.version}`}
        >
          Edit
        </Link>
      </td>
    </tr>
  );
}
```

## Acceptance Criteria

- [ ] Policy list page renders a section per policy with name, active version badge, version table (version, status, author, activated_at) (AC-1)
- [ ] `activated_at` displays as human-readable relative time (AC-1)
- [ ] `PolicyActiveBadge` has `aria-label="Active version: N"` (WCAG 2.1 AA)
- [ ] `RequireSecurityOfficer` redirects to `/403` for users without `SECURITY_OFFICER` or `ADMIN` role (AC-7)
- [ ] Role check is case-insensitive (`security_officer`, `SECURITY_OFFICER`, `admin`, `ADMIN` all grant access) (AC-7)
- [ ] `GET /v1/policies` backend route is accessible only to `admin`-role JWT holders (the `require_admin_role` guard applies to all policy routes)
- [ ] All table headers have `scope="col"`; section has `aria-labelledby` (WCAG 2.1 AA)

## Dependencies

- TASK-US039-01 — `ADMIN_ROUTES`, `AuthContext`, `api` axios instance
- US-033 TASK-US033-02 — `PolicyRepository.list_all_with_versions()` must be implemented
- US-033 TASK-US033-04 — existing policy router extended (not replaced)

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] React Testing Library tests: list renders, role guard redirects non-officer users
