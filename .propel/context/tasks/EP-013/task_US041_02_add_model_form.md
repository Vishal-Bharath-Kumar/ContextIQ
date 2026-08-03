# TASK-US041-02 — Add Model Form (LiteLLM Format, Capability Tags, Validation)

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US041-02 |
| User Story | US-041 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the `AddModelPage` (AC-2) — a single-page form that registers a new AI model via `POST /v1/models`. The form collects all `ModelRegistration` fields: model ID (LiteLLM format), provider, context window size (integer), cost per 1k tokens (decimal), latency tier (select), and capability tags (checkbox group). React Hook Form + Zod handle validation; `useCreateModel` mutation submits the payload.

## Implementation Details

**Technology:** React 18, TypeScript, React Hook Form v7, Zod v3, TanStack Query v5 (`useMutation`)

**File locations:**
- `frontend/admin-portal/src/pages/models/AddModelPage.tsx`
- `frontend/admin-portal/src/services/modelService.ts` — extend with `useCreateModel`

---

### Zod schema

```ts
// frontend/admin-portal/src/schemas/addModelSchema.ts
import { z } from "zod";

// LiteLLM model ID format: "provider/model-name" OR bare "model-name"
// Examples: "gpt-4o", "anthropic/claude-3-haiku", "azure/gpt-4-turbo"
const LITELLM_MODEL_ID_REGEX = /^[a-zA-Z0-9\-_./:]+$/;

export const CAPABILITY_OPTIONS = [
  "chat", "completion", "embedding",
  "code", "summarization", "vision", "function_call",
] as const;

export type Capability = typeof CAPABILITY_OPTIONS[number];

export const addModelSchema = z.object({
  model_id: z
    .string()
    .min(1, "Model ID is required")
    .max(128)
    .regex(LITELLM_MODEL_ID_REGEX, "Use LiteLLM format: provider/model or model-name"),
  provider:           z.string().min(1, "Provider is required").max(64),
  context_window:     z.coerce.number().int().positive("Must be a positive integer"),
  cost_per_1k_tokens: z.coerce.number().min(0, "Cost cannot be negative"),
  latency_tier:       z.enum(["fast", "medium", "slow"]),
  capabilities:       z
    .array(z.enum(CAPABILITY_OPTIONS))
    .min(1, "Select at least one capability"),
});

export type AddModelFields = z.infer<typeof addModelSchema>;
```

---

### `useCreateModel` mutation

```ts
// frontend/admin-portal/src/services/modelService.ts  (extend)
import type { AddModelFields } from "../schemas/addModelSchema";

export function useCreateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AddModelFields) =>
      api.post<ModelDefinition>("/v1/models", payload).then((r) => r.data),
    onSuccess:  () => qc.invalidateQueries({ queryKey: MODEL_KEYS.all }),
  });
}
```

---

### `AddModelPage`

```tsx
// frontend/admin-portal/src/pages/models/AddModelPage.tsx
import { useNavigate }        from "react-router-dom";
import { useForm, Controller } from "react-hook-form";
import { zodResolver }        from "@hookform/resolvers/zod";
import { useCreateModel }     from "../../services/modelService";
import {
  addModelSchema, CAPABILITY_OPTIONS, type AddModelFields,
} from "../../schemas/addModelSchema";

const LATENCY_TIERS = [
  { value: "fast",   label: "Fast   (p95 < 500 ms)"   },
  { value: "medium", label: "Medium (p95 500 ms – 2 s)" },
  { value: "slow",   label: "Slow   (p95 > 2 s)"      },
] as const;

const PROVIDER_SUGGESTIONS = [
  "openai", "anthropic", "azure", "google", "cohere", "mistral",
];

export default function AddModelPage() {
  const navigate = useNavigate();
  const { mutate: create, isPending, error } = useCreateModel();

  const { register, handleSubmit, control, formState: { errors } } =
    useForm<AddModelFields>({
      resolver:      zodResolver(addModelSchema),
      defaultValues: { capabilities: [], latency_tier: "medium" },
    });

  const onSubmit = (data: AddModelFields) =>
    create(data, { onSuccess: () => navigate("/models") });

  const isConflict = (error as any)?.response?.status === 409;

  return (
    <main aria-labelledby="add-model-heading">
      <h1 id="add-model-heading" className="text-2xl font-semibold mb-6">
        Register AI Model
      </h1>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="max-w-xl space-y-5">

        {/* Model ID */}
        <div>
          <label htmlFor="model_id" className="block text-sm font-medium mb-1">
            Model ID <span aria-hidden="true">*</span>
          </label>
          <input
            id="model_id"
            list="model-id-suggestions"
            placeholder="gpt-4o or anthropic/claude-3-haiku"
            aria-describedby={errors.model_id ? "model_id_err" : "model_id_hint"}
            {...register("model_id")}
            className="input-field w-full font-mono"
          />
          {/* datalist for common model IDs — not exhaustive */}
          <datalist id="model-id-suggestions">
            <option value="gpt-4o" />
            <option value="gpt-4o-mini" />
            <option value="anthropic/claude-3-5-sonnet" />
            <option value="anthropic/claude-3-haiku" />
            <option value="google/gemini-1.5-pro" />
          </datalist>
          <p id="model_id_hint" className="text-xs text-gray-400 mt-0.5">
            Use LiteLLM format — see{" "}
            <a
              href="https://docs.litellm.ai/docs/providers"
              target="_blank"
              rel="noreferrer noopener"
              className="underline"
            >
              LiteLLM provider docs
            </a>
          </p>
          {errors.model_id && (
            <p id="model_id_err" role="alert" className="text-red-600 text-xs mt-1">
              {errors.model_id.message}
            </p>
          )}
          {isConflict && (
            <p role="alert" className="text-red-600 text-xs mt-1">
              A model with this ID is already registered.
            </p>
          )}
        </div>

        {/* Provider */}
        <div>
          <label htmlFor="provider" className="block text-sm font-medium mb-1">
            Provider <span aria-hidden="true">*</span>
          </label>
          <input
            id="provider"
            list="provider-suggestions"
            placeholder="openai"
            {...register("provider")}
            className="input-field w-full"
          />
          <datalist id="provider-suggestions">
            {PROVIDER_SUGGESTIONS.map((p) => <option key={p} value={p} />)}
          </datalist>
          {errors.provider && (
            <p role="alert" className="text-red-600 text-xs mt-1">{errors.provider.message}</p>
          )}
        </div>

        {/* Context window + cost row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="context_window" className="block text-sm font-medium mb-1">
              Context window (tokens) <span aria-hidden="true">*</span>
            </label>
            <input
              id="context_window"
              type="number"
              min={1}
              placeholder="128000"
              {...register("context_window")}
              className="input-field w-full"
            />
            {errors.context_window && (
              <p role="alert" className="text-red-600 text-xs mt-1">{errors.context_window.message}</p>
            )}
          </div>
          <div>
            <label htmlFor="cost_per_1k_tokens" className="block text-sm font-medium mb-1">
              Cost per 1k tokens (USD) <span aria-hidden="true">*</span>
            </label>
            <input
              id="cost_per_1k_tokens"
              type="number"
              step="0.0001"
              min={0}
              placeholder="0.0025"
              {...register("cost_per_1k_tokens")}
              className="input-field w-full"
            />
            {errors.cost_per_1k_tokens && (
              <p role="alert" className="text-red-600 text-xs mt-1">{errors.cost_per_1k_tokens.message}</p>
            )}
          </div>
        </div>

        {/* Latency tier */}
        <div>
          <label htmlFor="latency_tier" className="block text-sm font-medium mb-1">
            Latency tier <span aria-hidden="true">*</span>
          </label>
          <select
            id="latency_tier"
            {...register("latency_tier")}
            className="input-field w-full"
          >
            {LATENCY_TIERS.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        {/* Capability tags */}
        <fieldset>
          <legend className="block text-sm font-medium mb-2">
            Capabilities <span aria-hidden="true">*</span>
          </legend>
          <div className="grid grid-cols-3 gap-2">
            <Controller
              name="capabilities"
              control={control}
              render={({ field }) => (
                <>
                  {CAPABILITY_OPTIONS.map((cap) => (
                    <label key={cap} className="flex items-center gap-1.5 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        value={cap}
                        checked={field.value.includes(cap)}
                        onChange={(e) => {
                          const checked = e.target.checked;
                          field.onChange(
                            checked
                              ? [...field.value, cap]
                              : field.value.filter((c) => c !== cap)
                          );
                        }}
                        className="rounded"
                      />
                      <span className="font-mono text-xs">{cap}</span>
                    </label>
                  ))}
                </>
              )}
            />
          </div>
          {errors.capabilities && (
            <p role="alert" className="text-red-600 text-xs mt-1">{errors.capabilities.message}</p>
          )}
        </fieldset>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => navigate("/models")}
            className="btn-secondary"
          >
            Cancel
          </button>
          <button type="submit" disabled={isPending} className="btn-primary">
            {isPending ? "Registering…" : "Register Model"}
          </button>
        </div>
      </form>
    </main>
  );
}
```

## Acceptance Criteria

- [ ] Form collects all 6 required fields: model_id, provider, context_window, cost_per_1k_tokens, latency_tier, capabilities (AC-2)
- [ ] Model ID field has a `<datalist>` with common LiteLLM IDs as autocomplete suggestions and a link to the LiteLLM provider docs (AC-2)
- [ ] Submitting with zero capabilities selected shows `role="alert"` error "Select at least one capability" (AC-2)
- [ ] HTTP 409 from `POST /v1/models` (duplicate model_id) renders "A model with this ID is already registered" error (AC-2)
- [ ] On success, the form navigates to `/models` and the list re-fetches (AC-2)
- [ ] Each form field has a `<label>` with matching `htmlFor`; required fields have `aria-describedby` wired to error paragraphs (WCAG 2.1 AA)
- [ ] Capability checkboxes are inside a `<fieldset>` with `<legend>` for screen readers (WCAG 2.1 AA)

## Dependencies

- TASK-US041-01 — `AddModelPage` lazy-loaded by `ADMIN_ROUTES`; `modelService.ts` extended
- US-018 TASK-US018-04 — `POST /v1/models` endpoint (returns 409 on duplicate)

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] Tests: capability validation error, 409 duplicate message, successful submit navigates away
