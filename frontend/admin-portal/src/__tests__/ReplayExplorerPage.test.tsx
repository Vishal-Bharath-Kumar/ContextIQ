/**
 * ReplayExplorerPage — React Testing Library tests.
 *
 * Verifies:
 *  - Heading and filter form are rendered (AC-1).
 *  - Trace items from the API appear in the table (AC-1).
 *  - Governance chip labels show correct "Blocked"/"Allowed" text.
 *  - "View" links point to the correct trace-detail route (AC-2).
 *  - Empty-state message when no traces are returned.
 *
 * Guard redirect behaviour (AC-4) is covered by RequireRoles.test.tsx;
 * the route-level RequireAuditor wrapper is tested there.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeAll, afterEach, afterAll } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AuthContext } from "../context/AuthContext";
import type { User } from "../context/AuthContext";
import { hasAnyRole as checkHasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import { ReplayExplorerPage } from "../pages/traces/ReplayExplorerPage";
import type { TraceListItem } from "../pages/traces/trace.models";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

const MOCK_ITEMS: TraceListItem[] = [
  {
    request_id:         "req-abc-123",
    user_id:            "user-1",
    timestamp:          "2026-07-09T12:00:00Z",
    intent:             "summarise",
    model_selected:     "gpt-4o",
    governance_blocked: false,
    opa_denied_count:   0,
    object_key:         "traces/req-abc-123.json",
  },
  {
    request_id:         "req-def-456",
    user_id:            "user-2",
    timestamp:          "2026-07-09T13:00:00Z",
    intent:             "classify",
    model_selected:     null,
    governance_blocked: true,
    opa_denied_count:   3,
    object_key:         "traces/req-def-456.json",
  },
];

const server = setupServer(
  http.get("/v1/traces", () =>
    HttpResponse.json({ items: MOCK_ITEMS, total: 2, limit: 25, offset: 0 })
  )
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeUser(id: string, email: string, roles: string[]): User {
  return { id, email, roles };
}

function buildMockContextValue(user: User | null) {
  return {
    user,
    isLoading: false,
    signIn:    async (_token: string) => {},
    signOut:   () => {},
    hasRole:    (role: PlatformRoleValue) =>
      user ? checkHasAnyRole(user.roles, [role]) : false,
    hasAnyRole: (roles: PlatformRoleValue[]) =>
      user ? checkHasAnyRole(user.roles, roles) : false,
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage(user: User | null) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={buildMockContextValue(user)}>
        <QueryClientProvider client={makeQueryClient()}>
          <ReplayExplorerPage />
        </QueryClientProvider>
      </AuthContext.Provider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ReplayExplorerPage", () => {
  it("renders the page heading and search filter form", () => {
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));
    expect(
      screen.getByRole("heading", { name: "Replay Explorer" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("search", { name: "Trace search filters" })
    ).toBeInTheDocument();
  });

  it("shows trace items returned by the API", async () => {
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));
    await waitFor(() => {
      expect(screen.getByText("summarise")).toBeInTheDocument();
      expect(screen.getByText("classify")).toBeInTheDocument();
    });
  });

  it("renders governance chip labels for blocked and allowed traces", async () => {
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));
    await waitFor(() => {
      expect(screen.getByText("Blocked")).toBeInTheDocument();
      expect(screen.getByText("Allowed")).toBeInTheDocument();
    });
  });

  it("renders View links pointing to the correct trace-detail route (AC-2)", async () => {
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));
    await waitFor(() => {
      const links = screen.getAllByRole("link", { name: /View trace detail/ });
      expect(links).toHaveLength(2);
      expect(links[0]).toHaveAttribute("href", "/traces/req-abc-123");
      expect(links[1]).toHaveAttribute("href", "/traces/req-def-456");
    });
  });

  it("shows empty-state message when the API returns no traces", async () => {
    server.use(
      http.get("/v1/traces", () =>
        HttpResponse.json({ items: [], total: 0, limit: 25, offset: 0 })
      )
    );
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));
    await waitFor(() => {
      expect(
        screen.getByText("No execution traces found.")
      ).toBeInTheDocument();
    });
  });

  it("shows pagination controls when results are present", async () => {
    renderPage(makeUser("u1", "auditor@test.com", ["auditor"]));
    await waitFor(() => {
      expect(
        screen.getByRole("navigation", { name: "Trace list pagination" })
      ).toBeInTheDocument();
    });
  });
});
