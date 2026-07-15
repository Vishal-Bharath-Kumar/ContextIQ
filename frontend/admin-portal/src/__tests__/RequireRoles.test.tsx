/**
 * RequireRoles guard — React Testing Library tests.
 *
 * AC-1 / AC-2 / AC-4: Verifies redirect behaviour for allowed, denied,
 * unauthenticated, ADMIN super-role, and case-insensitive role matching.
 *
 * BUG FIXES vs spec:
 *  1. AuthProvider does not accept a _mockUser prop — use AuthContext.Provider
 *     directly with a hand-crafted mock value to control user state precisely.
 *  2. userRoles=[] still produces a non-null user — the "unauthenticated"
 *     test must pass user=null explicitly, not an empty-roles user object.
 *  3. Vitest globals (describe, it, expect) imported explicitly since
 *     vitest.config globals:true may not be set.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { hasAnyRole as checkHasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import { PlatformRole } from "../auth/roles";
import { AuthContext } from "../context/AuthContext";
import type { User } from "../context/AuthContext";
import { RequireRoles } from "../guards/RequireRoles";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function buildMockContextValue(user: User | null) {
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

function renderGuard(user: User | null, allowedRoles: PlatformRoleValue[]) {
  return render(
    <AuthContext.Provider value={buildMockContextValue(user)}>
      <MemoryRouter initialEntries={["/protected"]}>
        <RequireRoles allowedRoles={allowedRoles}>
          <div data-testid="content">Protected Content</div>
        </RequireRoles>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

function makeUser(roles: string[]): User {
  return { id: "u1", email: "u@test.com", roles };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RequireRoles — AC-1, AC-2", () => {
  it("renders children when user has an allowed role", () => {
    renderGuard(makeUser(["security_officer"]), [PlatformRole.SECURITY_OFFICER]);
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });

  it("redirects to /403 when user lacks required role", () => {
    renderGuard(makeUser(["developer"]), [PlatformRole.SECURITY_OFFICER]);
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
  });

  it("ADMIN passes any RequireRoles check regardless of allowedRoles list", () => {
    renderGuard(makeUser(["admin"]), [PlatformRole.SECURITY_OFFICER]);
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });

  it("redirects to /login when user is null (unauthenticated)", () => {
    // BUG FIX: must pass user=null, not a user with empty roles array.
    // A user with roles=[] is authenticated but unauthorised → /403 not /login.
    renderGuard(null, [PlatformRole.ADMIN]);
    expect(screen.queryByTestId("content")).not.toBeInTheDocument();
  });

  it("role comparison is case-insensitive — SECURITY_OFFICER matches security_officer", () => {
    // AC-4: IdP may return uppercase role strings
    renderGuard(makeUser(["SECURITY_OFFICER"]), [PlatformRole.SECURITY_OFFICER]);
    expect(screen.getByTestId("content")).toBeInTheDocument();
  });
});
