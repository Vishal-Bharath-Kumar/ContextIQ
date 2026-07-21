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

const MOCK_ENTRIES = [
  {
    id:            "aaa-111",
    action:        "policy.created",
    resource_type: "policy",
    resource_id:   "pol-1",
    actor_user_id: "user-1",
    ip_address:    "10.0.0.1",
    before_state:  null,
    after_state:   { name: "p1" },
    timestamp:     "2026-07-09T12:00:00Z",
    row_hash:      "abc123",
  },
];

const server = setupServer(
  http.get("/api/v1/audit-log", () =>
    HttpResponse.json({ items: MOCK_ENTRIES, next_cursor: null })
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
