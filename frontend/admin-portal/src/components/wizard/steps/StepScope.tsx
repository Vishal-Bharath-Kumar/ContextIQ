import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  scopeSchema,
  type ScopeFields,
} from "../../../schemas/connectorWizard";

interface Props {
  connectorType: string;
  defaults: Partial<ScopeFields>;
  onNext: (data: ScopeFields) => void;
  onBack: () => void;
}

// Connector-type-specific scope placeholder text
const SCOPE_PLACEHOLDERS: Record<string, string> = {
  github: "org/repo (e.g. acme-corp/backend-api)",
  confluence: "Space key (e.g. ENG)",
  jira: "Project key (e.g. PLATFORM)",
  grafana: "Folder or dashboard UID (e.g. observability)",
};

const SCOPE_LABELS: Record<string, string> = {
  github: "Repository (org/repo)",
  confluence: "Confluence space key",
  jira: "Jira project key",
  grafana: "Grafana folder or dashboard UID",
};

export function StepScope({ connectorType, defaults, onNext, onBack }: Props) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ScopeFields>({
    resolver: zodResolver(scopeSchema),
    defaultValues: defaults,
  });

  const label = SCOPE_LABELS[connectorType] ?? "Scope";
  const placeholder =
    SCOPE_PLACEHOLDERS[connectorType] ?? "Enter scope value";

  return (
    <form onSubmit={handleSubmit(onNext)} noValidate>
      <fieldset>
        <legend className="text-lg font-medium mb-4">Scope</legend>

        <label htmlFor="scope" className="block text-sm font-medium mb-1">
          {label} <span aria-hidden="true">*</span>
        </label>
        <input
          id="scope"
          type="text"
          placeholder={placeholder}
          aria-required="true"
          aria-describedby={errors.scope ? "scope_error" : undefined}
          className="input-field w-full"
          {...register("scope")}
        />
        {errors.scope && (
          <p
            id="scope_error"
            role="alert"
            className="text-red-600 text-xs mt-1"
          >
            {errors.scope.message}
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
