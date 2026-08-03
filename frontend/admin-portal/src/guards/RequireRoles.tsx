import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { hasAnyRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";
import { useAuth } from "../context/AuthContext";

interface Props {
  /** Roles that are allowed to see the wrapped content. ADMIN always passes. */
  allowedRoles: PlatformRoleValue[];
  children: ReactNode;
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
