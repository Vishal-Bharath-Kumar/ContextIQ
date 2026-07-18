import { z } from "zod";

export const typeSchema = z.object({
  connector_type: z.enum(["github", "confluence", "jira", "grafana"]),
  name: z.string().min(2, "Name must be at least 2 characters"),
});

export const credentialsSchema = z.object({
  // vault_path is the path in Vault where the secret is stored.
  // The UI sends ONLY the vault_path — actual credentials are never transmitted
  // through the Admin Portal API (AC-2: "stored in Vault").
  vault_path: z
    .string()
    .regex(
      /^secret\/data\/[a-z0-9\-/_]+$/,
      "Must be a valid Vault secret path"
    ),
});

export const scopeSchema = z.object({
  scope: z.string().min(1, "Scope is required"),
  // connector_type-specific: repo org/name for GitHub, space key for Confluence, etc.
});

const CRON_REGEX =
  /^(@(annually|yearly|monthly|weekly|daily|hourly)|((([\d,\-*\/]+)\s+){4}[\d,\-*\/]+))$/;

export const scheduleSchema = z.object({
  sync_schedule: z
    .string()
    .regex(CRON_REGEX, "Enter a valid cron expression, e.g. 0 2 * * *"),
});

export type TypeFields = z.infer<typeof typeSchema>;
export type CredentialFields = z.infer<typeof credentialsSchema>;
export type ScopeFields = z.infer<typeof scopeSchema>;
export type ScheduleFields = z.infer<typeof scheduleSchema>;

// Composed payload sent to POST /v1/knowledge-sources
export const connectorCreateSchema = typeSchema
  .merge(credentialsSchema)
  .merge(scopeSchema)
  .merge(scheduleSchema);
export type ConnectorCreatePayload = z.infer<typeof connectorCreateSchema>;
