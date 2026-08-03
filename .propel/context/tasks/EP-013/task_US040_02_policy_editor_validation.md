# TASK-US040-02 — Policy Editor: Syntax-Highlighted Rego Editor with Inline OPA Validation

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US040-02 |
| User Story | US-040 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 2 |
| Status | Draft |

## Description

Implement the `PolicyDetailPage` containing a CodeMirror 6 editor with Rego syntax highlighting and a debounced inline OPA validation pipeline (AC-2). On each editor change (after a 600 ms debounce), the Rego body is sent to a `POST /v1/policies/validate` backend endpoint; parse errors are rendered as inline markers on the affected lines. The page also provides the "Save Draft" form using React Hook Form + Zod.

## Implementation Details

**Technology:** React 18, TypeScript, CodeMirror 6 (`@codemirror/state`, `@codemirror/view`, `@uiw/codemirror-extensions-langs`), React Hook Form v7, Zod v3, TanStack Query v5 (`useMutation`)

**File locations:**
- `frontend/admin-portal/src/pages/policies/PolicyDetailPage.tsx` — page container
- `frontend/admin-portal/src/components/policies/RegoEditor.tsx` — CodeMirror wrapper
- `frontend/admin-portal/src/components/policies/ValidationErrorPanel.tsx` — inline error display
- `frontend/admin-portal/src/services/policyService.ts` — extend with `useValidateRego`, `usePolicyDetail`
- `src/api/admin/routes/policies.py` — add `POST /v1/policies/validate` (backend extension)

---

### Backend: `POST /v1/policies/validate`

```python
# src/api/admin/routes/policies.py  (extend existing router — add validate route)
from pydantic import BaseModel as _Base

class RegoValidateRequest(_Base):
    rego_body: str

class RegoValidateResponse(_Base):
    valid:   bool
    errors:  list[str]   # list of OPA parse error messages (empty when valid=True)

@router.post(
    "/validate",
    response_model = RegoValidateResponse,
    summary        = "Dry-run validate a Rego body against OPA (AC-2).",
)
async def validate_rego(
    body:    RegoValidateRequest,
    claims:  AdminClaims,
    session: AsyncSession = Depends(get_async_session),
) -> RegoValidateResponse:
    """
    Pushes the Rego body to OPA via PUT /v1/policies/{tmp_name} (dry-run) then
    immediately deletes it. Returns validation errors without persisting anything.
    Uses the existing RegoValidator from TASK-US033-02.
    """
    import httpx
    validator = RegoValidator(
        client   = httpx.AsyncClient(),
        opa_base = settings.opa_base_url,
    )
    result = await validator.validate(body.rego_body)
    return RegoValidateResponse(valid=result.valid, errors=result.errors)
```

---

### `policyService.ts` extensions

```ts
// frontend/admin-portal/src/services/policyService.ts  (extend)

export interface RegoValidationResult {
  valid:  boolean;
  errors: string[];
}

/** Validate Rego against OPA without persisting. */
export function useValidateRego() {
  return useMutation({
    mutationFn: (regoBody: string) =>
      api
        .post<RegoValidationResult>("/v1/policies/validate", { rego_body: regoBody })
        .then((r) => r.data),
  });
}

export function usePolicyDetail(policyId: string | undefined) {
  return useQuery({
    queryKey: POLICY_KEYS.detail(policyId ?? ""),
    queryFn:  () =>
      api.get<PolicyListItem>(`/v1/policies/${policyId}`).then((r) => r.data),
    enabled:  Boolean(policyId),
  });
}
```

---

### `RegoEditor` — CodeMirror 6 wrapper

```tsx
// frontend/admin-portal/src/components/policies/RegoEditor.tsx
import { useEffect, useRef, useCallback }         from "react";
import { EditorState, Extension }                 from "@codemirror/state";
import { EditorView, keymap, lineNumbers }        from "@codemirror/view";
import { defaultKeymap, historyKeymap, history }  from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";
// Rego language extension — community package; falls back to plain text if unavailable
import { rego }                                   from "@codemirror/lang-rego";

interface Props {
  value:    string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  ariaLabel?: string;
}

export function RegoEditor({ value, onChange, readOnly = false, ariaLabel }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef      = useRef<EditorView | null>(null);

  const onChangeCallback = useCallback(onChange, [onChange]);

  useEffect(() => {
    if (!containerRef.current) return;

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        onChangeCallback(update.state.doc.toString());
      }
    });

    const extensions: Extension[] = [
      history(),
      lineNumbers(),
      syntaxHighlighting(defaultHighlightStyle),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      updateListener,
      EditorView.editable.of(!readOnly),
      EditorView.contentAttributes.of({
        "aria-label": ariaLabel ?? "Rego policy editor",
        "aria-multiline": "true",
        role: "textbox",
      }),
    ];

    // Use rego() extension if available, otherwise plain text
    try { extensions.push(rego()); } catch { /* package optional */ }

    const state = EditorState.create({
      doc: value,
      extensions,
    });

    viewRef.current = new EditorView({
      state,
      parent: containerRef.current,
    });

    return () => {
      viewRef.current?.destroy();
      viewRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);   // Mount once; value updates handled below

  // Sync external value changes (e.g. loading a version)
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
    }
  }, [value]);

  return (
    <div
      ref={containerRef}
      className="border rounded font-mono text-sm min-h-[400px] focus-within:ring-2 focus-within:ring-blue-500"
      data-testid="rego-editor"
    />
  );
}
```

---

### `ValidationErrorPanel`

```tsx
// frontend/admin-portal/src/components/policies/ValidationErrorPanel.tsx
interface Props {
  errors:    string[];
  isLoading: boolean;
}

export function ValidationErrorPanel({ errors, isLoading }: Props) {
  if (isLoading) {
    return (
      <p role="status" aria-live="polite" className="text-xs text-gray-400 mt-1">
        Validating…
      </p>
    );
  }

  if (errors.length === 0) {
    return (
      <p role="status" aria-live="polite" className="text-xs text-green-700 mt-1">
        ✓ Valid Rego
      </p>
    );
  }

  return (
    <ul
      role="alert"                // immediate announcement on error (AC-2, WCAG 2.1 AA)
      aria-label="Rego validation errors"
      className="mt-2 space-y-1"
    >
      {errors.map((err, i) => (
        <li key={i} className="text-xs text-red-600 font-mono bg-red-50 px-2 py-1 rounded">
          {err}
        </li>
      ))}
    </ul>
  );
}
```

---

### `PolicyDetailPage` — editor integration with 600 ms debounce

```tsx
// frontend/admin-portal/src/pages/policies/PolicyDetailPage.tsx
import { useState, useEffect, useRef }    from "react";
import { useParams, useSearchParams }     from "react-router-dom";
import { useForm }                        from "react-hook-form";
import { zodResolver }                    from "@hookform/resolvers/zod";
import { z }                              from "zod";
import { RegoEditor }                     from "../../components/policies/RegoEditor";
import { ValidationErrorPanel }           from "../../components/policies/ValidationErrorPanel";
import { ActivatePolicyDialog }           from "../../components/policies/ActivatePolicyDialog";   // Task 3
import { RollbackDropdown }               from "../../components/policies/RollbackDropdown";       // Task 3
import { PreviewImpactPanel }             from "../../components/policies/PreviewImpactPanel";     // Task 4
import { useValidateRego, useCreatePolicy, usePolicyDetail } from "../../services/policyService";

const draftSchema = z.object({
  name:        z.string().min(1, "Name is required"),
  version:     z.string().regex(/^\d+\.\d+\.\d+$/, "Use semantic versioning, e.g. 1.0.0"),
  description: z.string().max(1024),
  rego_body:   z.string().min(1, "Rego body cannot be empty"),
});
type DraftFields = z.infer<typeof draftSchema>;

export default function PolicyDetailPage() {
  const { id }               = useParams<{ id: string }>();
  const [searchParams]       = useSearchParams();
  const { data: policy }     = usePolicyDetail(id);
  const { mutate: validate, isPending: isValidating, data: validationResult } = useValidateRego();
  const { mutate: create,   isPending: isSaving }                             = useCreatePolicy();

  const [regoBody, setRegoBody] = useState("");
  const debounceRef             = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { register, handleSubmit, setValue, formState: { errors } } = useForm<DraftFields>({
    resolver: zodResolver(draftSchema),
  });

  // Populate from policy data when loading an existing version
  useEffect(() => {
    const version = searchParams.get("version");
    if (policy && version) {
      const v = policy.versions.find((vv) => vv.version === version);
      if (v) {
        setValue("name",        policy.name);
        setValue("version",     v.version);
        setValue("description", v.description);
        setValue("rego_body",   v.rego_body ?? "");
        setRegoBody(v.rego_body ?? "");
      }
    }
  }, [policy, searchParams, setValue]);

  // Debounced OPA validation (AC-2: "parse errors shown immediately")
  const handleRegoChange = (val: string) => {
    setRegoBody(val);
    setValue("rego_body", val, { shouldValidate: false });

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      if (val.trim().length > 0) validate(val);
    }, 600);
  };

  const onSubmit = (data: DraftFields) =>
    create({ ...data, rego_body: regoBody });

  const isNew = !id;

  return (
    <main aria-labelledby="policy-editor-heading">
      <div className="flex items-center justify-between mb-6">
        <h1 id="policy-editor-heading" className="text-2xl font-semibold">
          {isNew ? "New Policy" : `Edit Policy — ${policy?.name ?? id}`}
        </h1>
        <div className="flex gap-2">
          {!isNew && policy && <PreviewImpactPanel policyId={id!} />}
          {!isNew && policy && <RollbackDropdown policy={policy} />}
          {!isNew && policy && <ActivatePolicyDialog policyId={id!} policyName={policy.name} />}
        </div>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="policy-name" className="block text-sm font-medium mb-1">
              Policy name <span aria-hidden="true">*</span>
            </label>
            <input id="policy-name" {...register("name")} className="input-field w-full" />
            {errors.name && <p role="alert" className="text-red-600 text-xs mt-1">{errors.name.message}</p>}
          </div>
          <div>
            <label htmlFor="policy-version" className="block text-sm font-medium mb-1">
              Version <span aria-hidden="true">*</span>
            </label>
            <input id="policy-version" {...register("version")} placeholder="1.0.0" className="input-field w-full" />
            {errors.version && <p role="alert" className="text-red-600 text-xs mt-1">{errors.version.message}</p>}
          </div>
        </div>

        <div>
          <label htmlFor="policy-description" className="block text-sm font-medium mb-1">
            Description
          </label>
          <textarea id="policy-description" rows={2} {...register("description")} className="input-field w-full" />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">
            Rego body <span aria-hidden="true">*</span>
          </label>
          {/* CodeMirror editor — not a native form element; value managed in state (AC-2) */}
          <RegoEditor
            value={regoBody}
            onChange={handleRegoChange}
            ariaLabel="Rego policy body"
          />
          <ValidationErrorPanel
            errors={validationResult?.errors ?? []}
            isLoading={isValidating}
          />
          {errors.rego_body && (
            <p role="alert" className="text-red-600 text-xs mt-1">{errors.rego_body.message}</p>
          )}
        </div>

        <button type="submit" disabled={isSaving} className="btn-primary">
          {isSaving ? "Saving…" : "Save Draft"}
        </button>
      </form>
    </main>
  );
}
```

## Acceptance Criteria

- [ ] Rego editor uses CodeMirror 6 with syntax highlighting applied to keywords, strings, and comments (AC-2)
- [ ] After 600 ms of no typing, the Rego body is sent to `POST /v1/policies/validate`; OPA parse errors appear as inline list items with `role="alert"` (AC-2)
- [ ] "Valid Rego" confirmation message appears when `errors` is empty and validation is complete (AC-2)
- [ ] Loading an existing policy version from the URL `?version=N` param pre-fills the editor (AC-1)
- [ ] "Save Draft" calls `POST /v1/policies` and invalidates the policy list cache
- [ ] Editor container has `role="textbox"` and `aria-label` for screen readers (WCAG 2.1 AA)
- [ ] `POST /v1/policies/validate` returns 200 with `{"valid": false, "errors": [...]}` when Rego is invalid — never returns 4xx for parse errors

## Dependencies

- TASK-US040-01 — `PolicyDetailPage` lazy-loaded by `ADMIN_ROUTES`; `policyService.ts` extended
- TASK-US039-01 — Admin Portal routing shell
- US-033 TASK-US033-02 — `RegoValidator.validate()` used by the new validate route

## Definition of Done

- [ ] `pnpm build` succeeds; no TypeScript errors
- [ ] Tests: debounce triggers mutation after 600 ms, error panel renders OPA errors, valid state shown
