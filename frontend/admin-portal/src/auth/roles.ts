/**
 * Mirror of src/auth/roles.py PlatformRole values.
 * Kept in sync with backend — if a role is renamed there, update here too.
 */
export const PlatformRole = {
  DEVELOPER:        "developer",
  PLATFORM_ENGINEER: "platform_engineer",
  DEVOPS_SRE:       "devops_sre",
  ADMIN:            "admin",
  SECURITY_OFFICER: "security_officer",
  MANAGER:          "manager",
  AUDITOR:          "auditor",
} as const;

export type PlatformRoleValue = typeof PlatformRole[keyof typeof PlatformRole];

/**
 * Returns true if userRoles contains at least one of allowedRoles
 * (case-insensitive). ADMIN always passes regardless of allowedRoles.
 */
export function hasAnyRole(
  userRoles: string[],
  allowedRoles: PlatformRoleValue[],
): boolean {
  const normalised = userRoles.map((r) => r.toLowerCase());
  if (normalised.includes(PlatformRole.ADMIN)) return true;
  return allowedRoles.some((r) => normalised.includes(r.toLowerCase()));
}
