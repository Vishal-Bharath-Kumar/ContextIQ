# TASK-US039-02 — Add Connector Wizard (Type Selection, Credentials, Scope, Schedule)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US039-02 |
| User Story | US-039 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the four-step "Add Connector" wizard (AC-2): (1) connector type selection, (2) credential entry with masked input fields whose values are stored in Vault via the `vault_path` field, (3) scope configuration (repository/space/project scoping), and (4) sync schedule input (cron expression or interval). The wizard uses React Hook Form with per-step Zod validation. Navigation is keyboard-accessible and WCAG 2.1 AA compliant (AC-7).

## Implementation Details

**Technology:** React 18, TypeScript, React Hook Form v7, Zod v3, TanStack Query v5 (`useMutation`)

**File locations:**
- `frontend/admin-portal/src/pages/connectors/AddConnectorPage.tsx` — page container
- `frontend/admin-portal/src/components/wizard/WizardStepper.tsx` — step indicator (ARIA progress)
- `frontend/admin-portal/src/components/wizard/steps/StepTypeSelection.tsx`
- `frontend/admin-portal/src/components/wizard/steps/StepCredentials.tsx`
- `frontend/admin-portal/src/components/wizard/steps/StepScope.tsx`
- `frontend/admin-portal/src/components/wizard/steps/StepSchedule.tsx`
- `frontend/admin-portal/src/services/connectorService.ts` — extend with `useCreateConnector`

---

### Zod schemas (per step)

```ts
// frontend/admin-portal/src/schemas/connectorWizard.ts
import { z } from "zod";

export const typeSchema = z.object({
  connector_type: z.enum(["github", "confluence", "jira", "grafana"]),
  name:           z.string().min(2, "Name must be at least 2 characters"),
});

export const credentialsSchema = z.object({
  // vault_path is the path in Vault where the secret is stored.
  // The UI sends ONLY the vault_path — actual credentials are never transmitted
  // through the Admin Portal API (AC-2: "stored in Vault").
  vault_path: z
    .string()
    .regex(/^secret\/data\/[a-z0-9\-/_]+$/, "Must be a valid Vault secret path"),
});

export const scopeSchema = z.object({
  scope: z.string().min(1, "Scope is required"),
  // connector_type-specific: repo org/name for GitHub, space key for Confluence, etc.
});

const CRON_REGEX = /^(@(annually|yearly|monthly|weekly|daily|hourly)|((([\d,\-*\/]+)\s+){4}[\d,\-*\/]+))$/;

export const scheduleSchema = z.object({
  sync_schedule: z
    .string()
    .regex(CRON_REGEX, "Enter a valid cron expression, e.g. 0 2 * * *"),
});

export type TypeFields       = z.infer<typeof typeSchema>;
export type CredentialFields = z.infer<typeof credentialsSchema>;
export type ScopeFields      = z.infer<typeof scopeSchema>;
export type ScheduleFields   = z.infer<typeof scheduleSchema>;

// Composed payload sent to POST /v1/knowledge-sources
export const connectorCreateSchema = typeSchema
  .merge(credentialsSchema)
  .merge(scopeSchema)
  .merge(scheduleSchema);
export type ConnectorCreatePayload = z.infer<typeof connectorCreateSchema>;
```

---

### `AddConnectorPage` — wizard state machine

```tsx
// frontend/admin-portal/src/pages/connectors/AddConnectorPage.tsx
import { useState }       from "react";
import { useNavigate }    from "react-router-dom";
import { useCreateConnector } from "../../services/connectorService";
import { WizardStepper }  from "../../components/wizard/WizardStepper";
import { StepTypeSelection } from "../../components/wizard/steps/StepTypeSelection";
import { StepCredentials }   from "../../components/wizard/steps/StepCredentials";
import { StepScope }         from "../../components/wizard/steps/StepScope";
import { StepSchedule }      from "../../components/wizard/steps/StepSchedule";
import type { ConnectorCreatePayload } from "../../schemas/connectorWizard";

const STEPS = ["Type", "Credentials", "Scope", "Schedule"] as const;

export default function AddConnectorPage() {
  const navigate = useNavigate();
  const [step, setStep]       = useState(0);
  const [payload, setPayload] = useState<Partial<ConnectorCreatePayload>>({});
  const { mutate: createConnector, isPending } = useCreateConnector();

  const advance = (data: Partial<ConnectorCreatePayload>) => {
    const merged = { ...payload, ...data };
    setPayload(merged);
    if (step < STEPS.length - 1) {
      setStep((s) => s + 1);
    } else {
      // Final step — submit
      createConnector(merged as ConnectorCreatePayload, {
        onSuccess: () => navigate("/connectors"),
      });
    }
  };

  const back = () => setStep((s) => Math.max(0, s - 1));

  return (
    <main aria-labelledby="add-connector-heading">
      <h1 id="add-connector-heading" className="text-2xl font-semibold mb-6">
        Add Connector
      </h1>

      {/* ARIA progress: announces step position to screen readers (AC-7) */}
      <WizardStepper
        steps={[...STEPS]}
        currentStep={step}
        aria-label="Add connector steps"
      />

      {step === 0 && <StepTypeSelection onNext={advance} defaults={payload} />}
      {step === 1 && <StepCredentials   onNext={advance} onBack={back} defaults={payload} connectorType={payload.connector_type!} />}
      {step === 2 && <StepScope         onNext={advance} onBack={back} defaults={payload} connectorType={payload.connector_type!} />}
      {step === 3 && <StepSchedule      onNext={advance} onBack={back} defaults={payload} isPending={isPending} />}
    </main>
  );
}
```

---

### `StepCredentials` — masked input with Vault path helper

```tsx
// frontend/admin-portal/src/components/wizard/steps/StepCredentials.tsx
import { useForm }        from "react-hook-form";
import { zodResolver }    from "@hookform/resolvers/zod";
import { credentialsSchema, type CredentialFields } from "../../../schemas/connectorWizard";

interface Props {
  connectorType: string;
  defaults:  Partial<CredentialFields>;
  onNext:    (data: CredentialFields) => void;
  onBack:    () => void;
}

// Connector-type-specific Vault path hint (shown as placeholder text, not pre-filled)
const VAULT_HINTS: Record<string, string> = {
  github:     "secret/data/connectors/github/my-org-pat",
  confluence: "secret/data/connectors/confluence/my-cloud-token",
  jira:       "secret/data/connectors/jira/my-cloud-token",
  grafana:    "secret/data/connectors/grafana/my-service-account",
};

export function StepCredentials({ connectorType, defaults, onNext, onBack }: Props) {
  const { register, handleSubmit, formState: { errors } } = useForm<CredentialFields>({
    resolver:      zodResolver(credentialsSchema),
    defaultValues: defaults,
  });

  return (
    <form onSubmit={handleSubmit(onNext)} noValidate>
      <fieldset>
        <legend className="text-lg font-medium mb-4">Credentials</legend>

        <p className="text-sm text-gray-500 mb-4">
          Credentials are stored in HashiCorp Vault. Enter the Vault secret path
          where the credential is (or will be) stored — the portal never receives
          the secret value directly.
        </p>

        <label htmlFor="vault_path" className="block text-sm font-medium mb-1">
          Vault secret path <span aria-hidden="true">*</span>
        </label>
        <input
          id="vault_path"
          type="text"           {/* Not type="password" — the path is not a secret */}
          placeholder={VAULT_HINTS[connectorType] ?? "secret/data/connectors/…"}
          aria-required="true"
          aria-describedby={errors.vault_path ? "vault_path_error" : undefined}
          className="input-field w-full"
          {...register("vault_path")}
        />
        {errors.vault_path && (
          <p id="vault_path_error" role="alert" className="text-red-600 text-xs mt-1">
            {errors.vault_path.message}
          </p>
        )}
      </fieldset>

      <div className="flex gap-3 mt-6">
        <button type="button" onClick={onBack} className="btn-secondary">Back</button>
        <button type="submit"                  className="btn-primary">Next</button>
      </div>
    </form>
  );
}
```

---

### `WizardStepper` — accessible step indicator

```tsx
// frontend/admin-portal/src/components/wizard/WizardStepper.tsx
interface Props {
  steps:       string[];
  currentStep: number;
}

export function WizardStepper({ steps, currentStep }: Props) {
  return (
    <nav aria-label="Add connector progress" className="mb-8">
      <ol className="flex gap-0" role="list">
        {steps.map((label, i) => {
          const state =
            i < currentStep  ? "complete" :
            i === currentStep ? "current"  : "upcoming";

          return (
            <li
              key={label}
              aria-current={state === "current" ? "step" : undefined}
              className={`flex-1 text-center text-sm font-medium py-2 border-b-2 ${
                state === "complete"  ? "border-green-500 text-green-700" :
                state === "current"   ? "border-blue-600 text-blue-700"  :
                                        "border-gray-200 text-gray-400"
              }`}
            >
              <span className="sr-only">
                {state === "complete" ? `${label} (completed)` :
                 state === "current"  ? `${label} (current step)` :
                                        label}
              </span>
              <span aria-hidden="true">{i + 1}. {label}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
```

---

### `useCreateConnector` mutation

```ts
// frontend/admin-portal/src/services/connectorService.ts  (extend existing file)
import type { ConnectorCreatePayload } from "../schemas/connectorWizard";

export function useCreateConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConnectorCreatePayload) =>
      api.post("/v1/knowledge-sources", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTOR_KEYS.all }),
  });
}
```

## Acceptance Criteria

- [ ] Step 1 renders a card grid of connector types (`github`, `confluence`, `jira`, `grafana`); selecting one and submitting advances to step 2 (AC-2)
- [ ] Step 2 collects `vault_path` only (no raw credential fields); the Vault path hint updates based on the selected connector type (AC-2: credentials stored in Vault)
- [ ] Step 3 collects `scope`; placeholder text is connector-type-aware (e.g. "org/repo" for GitHub) (AC-2)
- [ ] Step 4 collects `sync_schedule` and validates against the cron regex; invalid cron shows inline error (AC-2)
- [ ] "Back" button restores the previous step's saved values without reset (AC-2)
- [ ] On final submit, `POST /v1/knowledge-sources` is called with all four fields merged (AC-2)
- [ ] Each step's `<legend>` / `<h2>` is announced by screen readers; errors use `role="alert"` (AC-7)
- [ ] `WizardStepper` marks the current step with `aria-current="step"` (AC-7)

## Dependencies

- TASK-US039-01 (`AddConnectorPage` is registered in `ADMIN_ROUTES`)
- US-025 TASK-US025-04 — `POST /v1/knowledge-sources` endpoint

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] React Testing Library tests: step navigation (next/back), cron validation error, form submission payload
