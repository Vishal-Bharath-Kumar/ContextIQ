/**
 * AuditLogPage — React Testing Library tests.
 *
 * AC-5: Verifies that the audit log page renders for an AUDITOR role user
 * and that non-AUDITOR roles (developer) are redirected away.
 *
 * BUG FIXES vs spec:
 *  1. AuthProvider does NOT accept a _mockUser prop — the component uses
 *     Keycloak-backed state internally.  Use AuthContext.Provider directly
 *     with a hand-crafted context value (same pattern as RequireRoles.test.tsx).
 *  2. Spec used { userId: ..., token: ... } which does not match the User
 *     interface { id, email, roles, name? }.  Fixed to { id, email, roles }.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeAll, afterEach, afterAll } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AuthContext } from "../context/AuthContext";
import type { User } from "../context/AuthContext";
import { hasAnyRole as checkHasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import { AuditLogPage } from "../pages/AuditLogPage";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

const MOCK_ENTRIES = Array.from({ length: 11 }, (_, index) => ({
  id:            `audit-${index + 1}`,
  action:        index === 0 ? "policy.created" : index === 10 ? "policy.deleted" : `policy.updated.${index + 1}`,
  resource_type: "policy",
  resource_id:   `pol-${index + 1}`,
  actor_user_id: `user-${index + 1}`,
  ip_address:    `10.0.0.${index + 1}`,
  before_state:  null,
  after_state:   { name: `p${index + 1}` },
  timestamp:     `2026-07-${String(index + 9).padStart(2, "0")}T12:00:00Z`,
  row_hash:      `hash-${index + 1}`,
}));

const SECOND_PAGE_CURSOR = "page-2";

const server = setupServer(
  http.get("/api/v1/audit-log", ({ request }) => {
    const url = new URL(request.url);
    const limit = url.searchParams.get("limit");
    const cursor = url.searchParams.get("cursor");

    if (limit !== "10") {
      return HttpResponse.json({ message: `Expected limit=10, received ${limit}` }, { status: 400 });
    }

    if (cursor === SECOND_PAGE_CURSOR) {
      return HttpResponse.json({ items: MOCK_ENTRIES.slice(10), next_cursor: null });
    }

    return HttpResponse.json({ items: MOCK_ENTRIES.slice(0, 10), next_cursor: SECOND_PAGE_CURSOR });
  })
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

function renderAuditPage(user: User | null) {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={buildMockContextValue(user)}>
        <QueryClientProvider client={makeQueryClient()}>
          <AuditLogPage />
        </QueryClientProvider>
      </AuthContext.Provider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests — AC-5
// ---------------------------------------------------------------------------

describe("AuditLogPage — AC-5", () => {
  it("renders audit table for AUDITOR role", async () => {
    renderAuditPage(makeUser("u1", "a@b.com", ["auditor"]));
    await waitFor(() =>
      expect(screen.getByText("policy.created")).toBeInTheDocument()
    );
  });

  it("renders actor_user_id and ip_address in the table", async () => {
    renderAuditPage(makeUser("u1", "a@b.com", ["auditor"]));
    await waitFor(() => {
      expect(screen.getByText("user-1")).toBeInTheDocument();
      expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
    });
  });

  it("paginates audit log entries 10 at a time", async () => {
    const user = userEvent.setup();

    renderAuditPage(makeUser("u1", "a@b.com", ["auditor"]));

    await waitFor(() => {
      expect(screen.getByText("policy.created")).toBeInTheDocument();
      expect(screen.getByRole("navigation", { name: "Audit log pagination" })).toBeInTheDocument();
      expect(screen.getByText("Page 1 · 10 entries per page")).toBeInTheDocument();
    });

    expect(screen.queryByText("policy.deleted")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => {
      expect(screen.getByText("policy.deleted")).toBeInTheDocument();
      expect(screen.getByText("Page 2 · 10 entries per page")).toBeInTheDocument();
    });

    expect(screen.queryByText("policy.created")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Previous page" }));

    await waitFor(() => {
      expect(screen.getByText("policy.created")).toBeInTheDocument();
      expect(screen.getByText("Page 1 · 10 entries per page")).toBeInTheDocument();
    });
  });

  it("does not show Audit Log content for DEVELOPER role", async () => {
    // BUG FIX (spec): spec checked "Audit Log" heading not in document.
    // RequireAuditor redirects developer to /403, so the h1 is not rendered.
    renderAuditPage(makeUser("u2", "b@b.com", ["developer"]));
    // Give React time to evaluate the guard before asserting absence
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /Audit Log/i })).not.toBeInTheDocument()
    );
  });
});
