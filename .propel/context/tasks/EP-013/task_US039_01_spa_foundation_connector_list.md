# TASK-US039-01 — React SPA Foundation and Connector List Page

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US039-01 |
| User Story | US-039 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Scaffold the Admin Portal React SPA and implement the Connector List page (AC-1). The SPA is the shared shell for EP-013 stories US-039, US-040, and US-041. The list page renders all connectors with their status badge (`active` / `inactive` / `error`), last sync timestamp (human-readable relative time), and indexed document count. WCAG 2.1 AA compliance is applied to all shell and list components (AC-7).

## Implementation Details

**Technology:** React 18, TypeScript 5, Vite 5, React Router v6, TanStack Query v5, Axios, date-fns, Tailwind CSS, Radix UI (accessible primitives)

**File locations:**
- `frontend/admin-portal/` — project root
- `frontend/admin-portal/src/main.tsx` — SPA entry point
- `frontend/admin-portal/src/App.tsx` — `RouterProvider` + `QueryClientProvider`
- `frontend/admin-portal/src/routes/index.tsx` — `ADMIN_ROUTES` lazy routes
- `frontend/admin-portal/src/context/AuthContext.tsx` — JWT auth context + `useAuth` hook
- `frontend/admin-portal/src/services/connectorService.ts` — TanStack Query hooks for connector API
- `frontend/admin-portal/src/pages/connectors/ConnectorListPage.tsx` — list page
- `frontend/admin-portal/src/components/connectors/ConnectorStatusBadge.tsx` — status badge
- `frontend/admin-portal/src/components/connectors/ConnectorRow.tsx` — table row

---

### SPA entry and routing

```tsx
// frontend/admin-portal/src/main.tsx
import React      from "react";
import ReactDOM   from "react-dom/client";
import { App }    from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

```tsx
// frontend/admin-portal/src/App.tsx
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider }    from "@tanstack/react-query";
import { AuthProvider }                        from "./context/AuthContext";
import { ADMIN_ROUTES }                        from "./routes";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 2 } },
});

const router = createBrowserRouter(ADMIN_ROUTES);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

```tsx
// frontend/admin-portal/src/routes/index.tsx
import { lazy }        from "react";
import type { RouteObject } from "react-router-dom";
import { AdminLayout } from "../layouts/AdminLayout";
import { RequireAdmin } from "../guards/RequireAdmin";

const ConnectorListPage  = lazy(() => import("../pages/connectors/ConnectorListPage"));
const AddConnectorPage   = lazy(() => import("../pages/connectors/AddConnectorPage"));   // US-039 Task 2
const PolicyListPage     = lazy(() => import("../pages/policies/PolicyListPage"));       // US-040
const ModelListPage      = lazy(() => import("../pages/models/ModelListPage"));          // US-041

export const ADMIN_ROUTES: RouteObject[] = [
  {
    path:    "/",
    element: <RequireAdmin><AdminLayout /></RequireAdmin>,
    children: [
      { index: true,              element: <ConnectorListPage /> },
      { path: "connectors",       element: <ConnectorListPage /> },
      { path: "connectors/add",   element: <AddConnectorPage /> },
      { path: "policies",         element: <PolicyListPage /> },
      { path: "models",           element: <ModelListPage /> },
    ],
  },
];
```

---

### Auth context

```tsx
// frontend/admin-portal/src/context/AuthContext.tsx
import { createContext, useContext, useState, useCallback, ReactNode } from "react";

interface AuthUser {
  userId:   string;
  email:    string;
  roles:    string[];
  token:    string;
}

interface AuthContextValue {
  user:   AuthUser | null;
  login:  (token: string) => void;
  logout: () => void;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => {
    const raw = sessionStorage.getItem("admin_user");   // sessionStorage — no XSS persistence
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  });

  const login = useCallback((token: string) => {
    // Decode JWT claims (RS256 — signature verified by backend, not here)
    const [, payload]  = token.split(".");
    const claims       = JSON.parse(atob(payload));
    const u: AuthUser  = {
      userId: claims.sub,
      email:  claims.email ?? "",
      roles:  claims.roles ?? [],
      token,
    };
    sessionStorage.setItem("admin_user", JSON.stringify(u));
    setUser(u);
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem("admin_user");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, logout, isAdmin: user?.roles.includes("admin") ?? false }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
};
```

---

### Connector API service + TanStack Query hooks

```ts
// frontend/admin-portal/src/services/connectorService.ts
import axios                         from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth }                   from "../context/AuthContext";

export interface ConnectorSummary {
  id:            string;
  name:          string;
  connector_type: string;
  status:        "active" | "inactive" | "syncing" | "error";
  last_sync_at:  string | null;   // ISO-8601
  document_count: number;
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api" });

// Inject Bearer token for every request
api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) {
    const { token } = JSON.parse(raw) as { token: string };
    cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

export const CONNECTOR_KEYS = {
  all:    ["connectors"]           as const,
  detail: (id: string) => ["connectors", id] as const,
};

export function useConnectors() {
  return useQuery({
    queryKey: CONNECTOR_KEYS.all,
    queryFn:  () =>
      api.get<ConnectorSummary[]>("/v1/knowledge-sources").then((r) => r.data),
  });
}

export function useToggleConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patch(`/v1/knowledge-sources/${id}/status`, {
        status: enabled ? "active" : "inactive",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTOR_KEYS.all }),
  });
}
```

---

### Connector list page

```tsx
// frontend/admin-portal/src/pages/connectors/ConnectorListPage.tsx
import { Suspense }                                  from "react";
import { Link }                                      from "react-router-dom";
import { useConnectors }                             from "../../services/connectorService";
import { ConnectorRow }                              from "../../components/connectors/ConnectorRow";

export default function ConnectorListPage() {
  const { data: connectors, isLoading, isError } = useConnectors();

  return (
    <main aria-labelledby="connectors-heading">
      <div className="flex items-center justify-between mb-6">
        <h1 id="connectors-heading" className="text-2xl font-semibold">
          Connectors
        </h1>
        <Link
          to="/connectors/add"
          className="btn-primary"
          aria-label="Add new connector"
        >
          Add Connector
        </Link>
      </div>

      {isLoading && <p role="status" aria-live="polite">Loading connectors…</p>}
      {isError   && <p role="alert">Failed to load connectors. Please retry.</p>}

      {connectors && (
        <table
          className="w-full border-collapse text-sm"
          aria-label="Registered connectors"
        >
          <thead>
            <tr>
              <th scope="col" className="text-left p-3">Name</th>
              <th scope="col" className="text-left p-3">Type</th>
              <th scope="col" className="text-left p-3">Status</th>
              <th scope="col" className="text-left p-3">Last Sync</th>
              <th scope="col" className="text-left p-3">Documents</th>
              <th scope="col" className="text-left p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {connectors.map((c) => (
              <ConnectorRow key={c.id} connector={c} />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
```

---

### `ConnectorStatusBadge`

```tsx
// frontend/admin-portal/src/components/connectors/ConnectorStatusBadge.tsx
interface Props { status: "active" | "inactive" | "syncing" | "error"; }

const BADGE: Record<Props["status"], { label: string; className: string }> = {
  active:   { label: "Active",   className: "badge-green"  },
  inactive: { label: "Inactive", className: "badge-grey"   },
  syncing:  { label: "Syncing",  className: "badge-blue"   },
  error:    { label: "Error",    className: "badge-red"     },
};

export function ConnectorStatusBadge({ status }: Props) {
  const { label, className } = BADGE[status];
  return (
    // aria-label carries semantic status for screen readers (WCAG 2.1 AA, AC-7)
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}
      aria-label={`Connector status: ${label}`}
    >
      {label}
    </span>
  );
}
```

---

### `ConnectorRow`

```tsx
// frontend/admin-portal/src/components/connectors/ConnectorRow.tsx
import { formatDistanceToNow } from "date-fns";
import { ConnectorStatusBadge } from "./ConnectorStatusBadge";
import { ConnectorToggle }      from "./ConnectorToggle";   // TASK-US039-03
import { TestConnectionButton } from "./TestConnectionButton"; // TASK-US039-03
import type { ConnectorSummary } from "../../services/connectorService";

interface Props { connector: ConnectorSummary; }

export function ConnectorRow({ connector }: Props) {
  const lastSync = connector.last_sync_at
    ? formatDistanceToNow(new Date(connector.last_sync_at), { addSuffix: true })
    : "Never";

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="p-3 font-medium">{connector.name}</td>
      <td className="p-3 capitalize">{connector.connector_type}</td>
      <td className="p-3"><ConnectorStatusBadge status={connector.status} /></td>
      <td className="p-3 text-gray-500">{lastSync}</td>
      <td className="p-3">{connector.document_count.toLocaleString()}</td>
      <td className="p-3 flex gap-2">
        <TestConnectionButton connectorId={connector.id} />
        <ConnectorToggle
          connectorId={connector.id}
          enabled={connector.status === "active"}
        />
      </td>
    </tr>
  );
}
```

## Acceptance Criteria

- [ ] `GET /v1/knowledge-sources` response populates the connector table (AC-1)
- [ ] Status badge renders the correct colour variant for `active`, `inactive`, `error`, and `syncing` (AC-1)
- [ ] `last_sync_at` renders as a human-readable relative time (e.g. "3 minutes ago") (AC-1)
- [ ] `document_count` is formatted with locale-aware thousand separators (AC-1)
- [ ] "Add Connector" button navigates to `/connectors/add` (AC-2 precondition)
- [ ] All table headers use `scope="col"`, all badges have `aria-label` (AC-7)
- [ ] `sessionStorage` is used (not `localStorage`) for JWT — minimises XSS persistence window

## Dependencies

- US-025 TASK-US025-04 — `GET /v1/knowledge-sources` API must be deployed
- TASK-US039-03 — `ConnectorToggle` and `TestConnectionButton` are imported but may be stubbed initially

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] `pnpm lint` reports zero `eslint` errors
- [ ] React Testing Library snapshot test passes for `ConnectorStatusBadge` (all 4 variants)
