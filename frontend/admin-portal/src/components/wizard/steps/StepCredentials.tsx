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
const VAULT_HINTS: Record<string, string> = {
  github: "secret/data/connectors/github/my-org-pat",
  confluence: "secret/data/connectors/confluence/my-cloud-token",
  jira: "secret/data/connectors/jira/my-cloud-token",
  grafana: "secret/data/connectors/grafana/my-service-account",
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
          htmlFor="vault_path"
          className="block text-sm font-medium mb-1"
        >
          Vault secret path <span aria-hidden="true">*</span>
        </label>
        <input
          id="vault_path"
          type="text"
          placeholder={
            VAULT_HINTS[connectorType] ?? "secret/data/connectors/…"
          }
          aria-required="true"
          aria-describedby={errors.vault_path ? "vault_path_error" : undefined}
          className="input-field w-full"
          {...register("vault_path")}
        />
        {errors.vault_path && (
          <p
            id="vault_path_error"
            role="alert"
            className="text-red-600 text-xs mt-1"
          >
            {errors.vault_path.message}
          </p>
        )}
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
