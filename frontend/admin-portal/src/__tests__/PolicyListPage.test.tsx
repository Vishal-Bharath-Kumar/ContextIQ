/**
 * PolicyListPage — React Testing Library tests.
 *
 * TASK-US040-01 DoD:
 *  - Policy list renders a section per policy with name, active version badge,
 *    and version table rows (version, status, author, activated).
 *  - RequireSecurityOfficer redirects users without SECURITY_OFFICER/ADMIN role
 *    to /403.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeAll, afterEach, afterAll } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { hasAnyRole as checkHasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import { AuthContext } from "../context/AuthContext";
import type { User } from "../context/AuthContext";
import { RequireSecurityOfficer } from "../guards";
import { PolicyListPage } from "../pages/policies/PolicyListPage";
import type { PolicyListItem } from "../services/policyService";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

const NOW = new Date().toISOString();
const WEEK_AGO = new Date(Date.now() - 7 * 86_400_000).toISOString();

const MOCK_POLICIES: PolicyListItem[] = [
  {
    id: "policy-uuid-1",
    name: "data-access-control",
    active_version: "1.1.0",
    versions: [
      {
        id: "ver-uuid-2",
        policy_group: "data-access-control",
        version: "1.1.0",
        status: "active",
        author: "alice@example.com",
        description: "Production version",
        activated_at: WEEK_AGO,
        created_at: WEEK_AGO,
      },
      {
        id: "ver-uuid-1",
        policy_group: "data-access-control",
        version: "1.0.0",
        status: "superseded",
        author: "bob@example.com",
        description: "Initial version",
        activated_at: null,
        created_at: NOW,
      },
    ],
    latest_author: "alice@example.com",
    activated_at: WEEK_AGO,
  },
];

const server = setupServer(
  http.get("/api/v1/policies", () => HttpResponse.json(MOCK_POLICIES))
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function buildMockAuthValue(user: User | null) {
  return {
    user,
    isLoading: false,
    signIn: async (_token: string) => {},
    signOut: () => {},
    hasRole: (role: PlatformRoleValue) =>
      user ? checkHasAnyRole(user.roles, [role]) : false,
    hasAnyRole: (roles: PlatformRoleValue[]) =>
      user ? checkHasAnyRole(user.roles, roles) : false,
  };
}

function makeUser(roles: string[]): User {
  return { id: "u1", email: "u@test.com", roles };
}

function renderPage(user: User | null) {
  render(
    <AuthContext.Provider value={buildMockAuthValue(user)}>
      <MemoryRouter initialEntries={["/policies"]}>
        <QueryClientProvider client={makeQueryClient()}>
          <PolicyListPage />
        </QueryClientProvider>
      </MemoryRouter>
    </AuthContext.Provider>
  );
}

function renderPageWithGuard(user: User | null) {
  render(
    <AuthContext.Provider value={buildMockAuthValue(user)}>
      <MemoryRouter initialEntries={["/policies"]}>
        <QueryClientProvider client={makeQueryClient()}>
          <RequireSecurityOfficer>
            <PolicyListPage />
          </RequireSecurityOfficer>
        </QueryClientProvider>
      </MemoryRouter>
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PolicyListPage — AC-1", () => {
  it("renders a section per policy with name and active version badge", async () => {
    renderPage(makeUser(["security_officer"]));
    expect(await screen.findByText("data-access-control")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Active version: 1.1.0")
    ).toBeInTheDocument();
  });

  it("renders version rows with version string, status, and author", async () => {
    renderPage(makeUser(["security_officer"]));
    expect(await screen.findByText("1.1.0")).toBeInTheDocument();
    expect(screen.getByText("1.0.0")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });

  it("shows loading state before data arrives", () => {
    server.use(
      http.get("/api/v1/policies", async () => {
        await new Promise(() => {}); // never resolves
        return HttpResponse.json([]);
      })
    );
    renderPage(makeUser(["security_officer"]));
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("table headers have scope='col'", async () => {
    renderPage(makeUser(["security_officer"]));
    await screen.findByText("data-access-control");
    const headers = screen.getAllByRole("columnheader");
    headers.forEach((th) => {
      expect(th).toHaveAttribute("scope", "col");
    });
  });
});

describe("RequireSecurityOfficer — AC-7", () => {
  it("renders page for security_officer role", async () => {
    renderPageWithGuard(makeUser(["security_officer"]));
    expect(await screen.findByText("data-access-control")).toBeInTheDocument();
  });

  it("renders page for ADMIN role (ADMIN always passes)", async () => {
    renderPageWithGuard(makeUser(["admin"]));
    expect(await screen.findByText("data-access-control")).toBeInTheDocument();
  });

  it("role check is case-insensitive — SECURITY_OFFICER grants access", async () => {
    renderPageWithGuard(makeUser(["SECURITY_OFFICER"]));
    expect(await screen.findByText("data-access-control")).toBeInTheDocument();
  });

  it("redirects developer role to /403 (page content not rendered)", () => {
    renderPageWithGuard(makeUser(["developer"]));
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
  });

  it("redirects unauthenticated user (null) — page content not rendered", () => {
    renderPageWithGuard(null);
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
  });
});
