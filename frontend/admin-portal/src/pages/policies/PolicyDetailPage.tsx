import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import {
  useCreatePolicy,
  usePolicyDetail,
  useValidateRego,
} from "../../services/policyService";
import { RegoEditor } from "../../components/policies/RegoEditor";
import { ValidationErrorPanel } from "../../components/policies/ValidationErrorPanel";
import { PreviewImpactPanel } from "../../components/policies/PreviewImpactPanel";
import { PolicyAuditTrailPanel } from "../../components/policies/PolicyAuditTrailPanel";
import { ActivatePolicyDialog } from "../../components/policies/ActivatePolicyDialog";
import { GlassCard } from "../../components/ui/GlassCard";
import { PageHeader } from "../../components/ui/PageHeader";

const DEFAULT_REGO_TEMPLATE = `package contextiq.example

default allow = false

allow {
  input.user.role == "admin"
}
`;

const policyFormSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  version: z.string().min(1, "Version is required"),
});

type PolicyFormFields = z.infer<typeof policyFormSchema>;

const VALIDATE_DEBOUNCE_MS = 600;

function PolicyDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const versionParam = searchParams.get("version");
  const isNew = !id;

  const { data: policy, isLoading: isPolicyLoading } = usePolicyDetail(id);
  const { mutateAsync: createPolicy, isPending: isSaving } = useCreatePolicy();
  const { mutate: validateRego, data: validation, isPending: isValidating } = useValidateRego();

  const [regoBody, setRegoBody] = useState(DEFAULT_REGO_TEMPLATE);
  const [saveError, setSaveError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<PolicyFormFields>({
    resolver: zodResolver(policyFormSchema),
    defaultValues: { name: "", description: "", version: "1.0.0" },
  });

  const selectedVersion = policy?.versions.find((v) => v.version === versionParam)
    ?? policy?.versions.find((v) => v.version === policy.active_version)
    ?? policy?.versions[0];

  useEffect(() => {
    if (!policy) return;
    reset({
      name: policy.name,
      description: selectedVersion?.description ?? "",
      version: selectedVersion?.version ?? policy.active_version ?? "1.0.0",
    });
    setRegoBody(selectedVersion?.rego_body ?? DEFAULT_REGO_TEMPLATE);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policy?.id, selectedVersion?.id]);

  function handleRegoChange(next: string) {
    setRegoBody(next);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => validateRego(next), VALIDATE_DEBOUNCE_MS);
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const onSubmit = async (fields: PolicyFormFields) => {
    setSaveError(null);
    try {
      await createPolicy({ ...fields, description: fields.description ?? "", rego_body: regoBody });
      navigate("/policies");
    } catch {
      setSaveError("Failed to save policy draft. Please try again.");
    }
  };

  const heading = isNew
    ? "New Policy"
    : policy
      ? `Edit Policy: ${policy.name}`
      : "Edit Policy";

  return (
    <main aria-labelledby="policy-detail-heading" className="page-layout max-w-4xl">
      <PageHeader
        headingId="policy-detail-heading"
        title={heading}
        subtitle="Author, validate, and preview OPA/Rego governance policies before activation."
        actions={
          !isNew && policy?.active_version ? (
            <ActivatePolicyDialog policyId={policy.id} policyName={policy.name} />
          ) : undefined
        }
      />

      {!isNew && isPolicyLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading policy…
        </p>
      )}

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
        <GlassCard className="p-6 space-y-4" delay={40}>
          {saveError && (
            <p role="alert" className="text-sm text-red-600">
              {saveError}
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="policy_name" className="form-label">
                Name
              </label>
              <input id="policy_name" type="text" className="input" {...register("name")} />
              {errors.name && (
                <p role="alert" className="mt-1 text-xs text-red-600">
                  {errors.name.message}
                </p>
              )}
            </div>
            <div>
              <label htmlFor="policy_version" className="form-label">
                Version
              </label>
              <input id="policy_version" type="text" className="input" {...register("version")} />
              {errors.version && (
                <p role="alert" className="mt-1 text-xs text-red-600">
                  {errors.version.message}
                </p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="policy_description" className="form-label">
              Description
            </label>
            <textarea
              id="policy_description"
              rows={2}
              className="input"
              {...register("description")}
            />
          </div>

          <div>
            <span className="form-label">Rego Policy Body</span>
            <RegoEditor value={regoBody} onChange={handleRegoChange} ariaLabel="Rego policy editor" />
            <ValidationErrorPanel errors={validation?.errors ?? []} isLoading={isValidating} />
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button type="submit" className="btn-primary" disabled={isSaving}>
              {isSaving ? "Saving…" : "Save Draft"}
            </button>
            {!isNew && <PreviewImpactPanel policyId={id!} regoBody={regoBody} />}
          </div>
        </GlassCard>

        {!isNew && id && (
          <GlassCard className="p-6" delay={80}>
            <PolicyAuditTrailPanel policyId={id} />
          </GlassCard>
        )}
      </form>
    </main>
  );
}

export { PolicyDetailPage };
export default PolicyDetailPage;
