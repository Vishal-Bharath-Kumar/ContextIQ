import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  credentialsSchema,
  type CredentialFields,
} from "../../../schemas/connectorWizard";

interface Props {
  connectorType: string;
  defaults: Partial<CredentialFields>;
  onNext: (data: CredentialFields) => void;
  onBack: () => void;
}

// Connector-type-specific Vault path hint (shown as placeholder text, not pre-filled)
// NOTE: bare KV v2 sub-path, no "secret/data/" prefix — the backend passes this
// straight to hvac with mount_point="secret" supplied separately.
const VAULT_HINTS: Record<string, string> = {
  github: "connectors/github/my-org-pat",
  confluence: "connectors/confluence/my-cloud-token",
  jira: "connectors/jira/my-cloud-token",
  grafana: "connectors/grafana/my-service-account",
};

export function StepCredentials({
  connectorType,
  defaults,
  onNext,
  onBack,
}: Props) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CredentialFields>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: defaults,
  });

  return (
    <form onSubmit={handleSubmit(onNext)} noValidate>
      <fieldset>
        <legend className="text-lg font-medium mb-4">Credentials</legend>

        <p className="text-sm text-gray-500 mb-4">
          Credentials are stored in HashiCorp Vault. Enter the Vault secret path
          where the credential is (or will be) stored — the portal never
          receives the secret value directly.
        </p>

        <label
          htmlFor="credentials_vault_path"
          className="block text-sm font-medium mb-1"
        >
          Vault secret path <span aria-hidden="true">*</span>
        </label>
        <input
          id="credentials_vault_path"
          type="text"
          placeholder={
            VAULT_HINTS[connectorType] ?? "secret/data/connectors/…"
          }
          aria-required="true"
          aria-describedby={
            errors.credentials_vault_path ? "credentials_vault_path_error" : undefined
          }
          className="input-field w-full"
          {...register("credentials_vault_path")}
        />
        {errors.credentials_vault_path && (
          <p
            id="credentials_vault_path_error"
            role="alert"
            className="text-red-600 text-xs mt-1"
          >
            {errors.credentials_vault_path.message}
          </p>
        )}

        <label
          htmlFor="credential_value"
          className="block text-sm font-medium mb-1 mt-4"
        >
          Credential value (optional)
        </label>
        <input
          id="credential_value"
          type="password"
          autoComplete="off"
          placeholder="Paste a PAT / API token — leave blank if already in Vault"
          aria-describedby="credential_value_hint"
          className="input-field w-full"
          {...register("credential_value")}
        />
        <p id="credential_value_hint" className="text-xs text-gray-500 mt-1">
          If provided, this is written directly to the Vault path above and is
          never stored by ContextIQ or shown again. Leave blank if you already
          placed the credential in Vault yourself.
        </p>
      </fieldset>

      <div className="flex gap-3 mt-6">
        <button type="button" onClick={onBack} className="btn-secondary">
          Back
        </button>
        <button type="submit" className="btn-primary">
          Next
        </button>
      </div>
    </form>
  );
}
