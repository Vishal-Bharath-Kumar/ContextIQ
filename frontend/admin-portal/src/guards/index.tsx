// BUG FIX: file is .tsx (not .ts) — contains JSX expressions.
import type { ReactNode } from "react";

import { PlatformRole } from "../auth/roles";
import { RequireRoles } from "./RequireRoles";

export { RequireRoles };

// Named guards for common permission groups — mirror the backend named callables
// from src/auth/rbac.py so frontend and backend policy definitions stay in sync.

export const RequireAdmin = ({ children }: { children: ReactNode }) => (
  <RequireRoles allowedRoles={[PlatformRole.ADMIN]}>{children}</RequireRoles>
);

export const RequirePlatformEngineer = ({ children }: { children: ReactNode }) => (
  <RequireRoles allowedRoles={[PlatformRole.PLATFORM_ENGINEER, PlatformRole.ADMIN]}>
    {children}
  </RequireRoles>
);

export const RequireSecurityOfficer = ({ children }: { children: ReactNode }) => (
  <RequireRoles allowedRoles={[PlatformRole.SECURITY_OFFICER, PlatformRole.ADMIN]}>
    {children}
  </RequireRoles>
);

export const RequireAuditor = ({ children }: { children: ReactNode }) => (
  <RequireRoles
    allowedRoles={[
      PlatformRole.AUDITOR,
      PlatformRole.DEVOPS_SRE,
      PlatformRole.SECURITY_OFFICER,
      PlatformRole.ADMIN,
    ]}
  >
    {children}
  </RequireRoles>
);

export const RequireManager = ({ children }: { children: ReactNode }) => (
  <RequireRoles
    allowedRoles={[
      PlatformRole.MANAGER,
      PlatformRole.PLATFORM_ENGINEER,
      PlatformRole.ADMIN,
    ]}
  >
    {children}
  </RequireRoles>
);
