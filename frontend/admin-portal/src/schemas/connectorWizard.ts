import { z } from "zod";

export const typeSchema = z.object({
  connector_type: z.enum(["github", "confluence", "jira", "grafana"]),
  name: z.string().min(2, "Name must be at least 2 characters"),
});

export const credentialsSchema = z.object({
  // credentials_vault_path is the KV v2 sub-path where the secret is stored,
  // e.g. "connectors/github/my-org-pat". The backend passes this value
  // straight to hvac's kv.v2 calls with mount_point="secret" supplied
  // separately (see vault_validator.py / connectors/*/auth.py) — do NOT
  // include a "secret/data/" prefix here, it would double-nest and never
  // resolve. The UI sends ONLY this path — actual credentials are never
  // transmitted through the Admin Portal API (AC-2: "stored in Vault").
  // Field name must match the backend's KnowledgeSourceCreate.credentials_vault_path.
  // Character set MUST match the backend's own validator
  // (KnowledgeSourceCreate.validate_vault_path_format in
  // src/knowledge_sources/schemas/knowledge_source.py: `^[a-zA-Z0-9/_\-.]+$`)
  // — it allows uppercase letters and dots (e.g. GitHub org names, semver-ish
  // secret names). A stricter frontend regex silently rejects otherwise-valid
  // paths before they ever reach the API.
  credentials_vault_path: z
    .string()
    .regex(
      /^[a-zA-Z0-9/_\-.]+$/,
      "Must be a valid Vault KV v2 path, e.g. connectors/github/my-org-pat"
    ),
  // Optional raw secret (e.g. a GitHub PAT). When provided, the backend
  // writes it to Vault at credentials_vault_path on your behalf — you do NOT
  // need to pre-populate Vault via the CLI. Leave blank if the secret is
  // already stored at that path. Never persisted by the Admin Portal itself;
  // it goes straight through to the API over HTTPS and then into Vault.
  // NOTE: blank string is stripped out before the POST body is sent (see
  // AddConnectorPage.tsx) — the backend rejects an empty credential_value.
  credential_value: z.string().optional(),
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
