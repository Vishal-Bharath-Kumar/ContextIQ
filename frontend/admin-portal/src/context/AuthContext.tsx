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

// Exported so tests can use AuthContext.Provider directly with mock values.
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function signIn(token: string): Promise<void> {
    setIsLoading(true);
    try {
      // TODO: decode JWT, populate user from claims (TASK-US004-01)
      void token;
    } finally {
      setIsLoading(false);
    }
  }

  function signOut(): void {
    setUser(null);
  }

  // Expose setUser so JWTAuthMiddleware integration (TASK-US004-01) can hydrate
  // the context after Keycloak token exchange without triggering a re-login.
  void setUser;

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
