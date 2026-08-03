import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";

import { hasAnyRole as checkHasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";

export interface User {
  id: string;
  email: string;
  roles: string[];
  name?: string;
}

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
  /** Returns true if the current user has the given role (ADMIN always passes). */
  hasRole: (role: PlatformRoleValue) => boolean;
  /** Returns true if the current user has at least one of the given roles (ADMIN always passes). */
  hasAnyRole: (roles: PlatformRoleValue[]) => boolean;
}

const STORAGE_KEY = "admin_user";

interface StoredSession {
  token: string;
  user: User;
}

/** Decode a JWT's payload (base64url) without verifying the signature —
 * the token is only ever trusted after the backend has already validated it
 * (it came back from POST /auth/dev-login, a real Keycloak-issued JWT, and
 * every subsequent API call is re-validated server-side by JWTAuthMiddleware).
 * This is purely to populate UI state (name, roles) client-side. */
function decodeJwtPayload(token: string): Record<string, unknown> {
  const [, payload] = token.split(".");
  if (!payload) throw new Error("Malformed JWT");
  const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  return JSON.parse(atob(padded)) as Record<string, unknown>;
}

function userFromToken(token: string): User {
  const claims = decodeJwtPayload(token);
  const realmRoles = (claims.realm_access as { roles?: string[] } | undefined)?.roles ?? [];
  return {
    id: String(claims.sub ?? ""),
    email: String(claims.email ?? claims.preferred_username ?? ""),
    roles: realmRoles,
    name: (claims.name as string | undefined) ?? (claims.preferred_username as string | undefined),
  };
}

function loadStoredSession(): StoredSession | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

// Exported so tests can use AuthContext.Provider directly with mock values.
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => loadStoredSession()?.user ?? null);
  const [isLoading, setIsLoading] = useState(false);

  async function signIn(token: string): Promise<void> {
    setIsLoading(true);
    try {
      const nextUser = userFromToken(token);
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user: nextUser }));
      setUser(nextUser);
    } finally {
      setIsLoading(false);
    }
  }

  function signOut(): void {
    sessionStorage.removeItem(STORAGE_KEY);
    setUser(null);
  }

  const value: AuthContextValue = {
    user,
    isLoading,
    signIn,
    signOut,
    hasRole: (role) => checkHasAnyRole(user?.roles ?? [], [role]),
    hasAnyRole: (roles) => checkHasAnyRole(user?.roles ?? [], roles),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}

