# TASK-US040-03 — Activate Confirmation Dialog and Rollback Version Dropdown

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US040-03 |
| User Story | US-040 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement `ActivatePolicyDialog` (AC-4) — a Radix UI `AlertDialog` confirmation modal that promotes the current policy version to `active` via `POST /v1/policies/{id}/activate` — and `RollbackDropdown` (AC-5) — a `Select` component listing all non-active versions that triggers `POST /v1/policies/{id}/rollback?version=N` on selection. Both components are keyboard-accessible and WCAG 2.1 AA compliant (AC-7). Audit trail logging is already handled server-side by `PolicyService` (US-033 TASK-US033-03); no additional backend work is required for AC-6.

## Implementation Details

**Technology:** React 18, TypeScript, TanStack Query v5 (`useMutation`), Radix UI `AlertDialog`, Radix UI `Select`

**File locations:**
- `frontend/admin-portal/src/components/policies/ActivatePolicyDialog.tsx`
- `frontend/admin-portal/src/components/policies/RollbackDropdown.tsx`
- `frontend/admin-portal/src/services/policyService.ts` — extend with `useActivatePolicy`, `useRollbackPolicy`

---

### TanStack Query mutations

```ts
// frontend/admin-portal/src/services/policyService.ts  (extend)

export function useActivatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policyId: string) =>
      api.post(`/v1/policies/${policyId}/activate`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: POLICY_KEYS.all }),
  });
}

export function useRollbackPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ policyId, version }: { policyId: string; version: string }) =>
      api.post(`/v1/policies/${policyId}/rollback?version=${encodeURIComponent(version)}`).then((r) => r.data),
    onSuccess: (_data, { policyId }) => {
      qc.invalidateQueries({ queryKey: POLICY_KEYS.all });
      qc.invalidateQueries({ queryKey: POLICY_KEYS.detail(policyId) });
    },
  });
}
```

---

### `ActivatePolicyDialog`

```tsx
// frontend/admin-portal/src/components/policies/ActivatePolicyDialog.tsx
import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { useState }     from "react";
import { useActivatePolicy } from "../../services/policyService";

interface Props {
  policyId:   string;
  policyName: string;
}

export function ActivatePolicyDialog({ policyId, policyName }: Props) {
  const [open, setOpen]               = useState(false);
  const { mutate: activate, isPending } = useActivatePolicy();

  const handleConfirm = () =>
    activate(policyId, { onSuccess: () => setOpen(false) });

  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        {/* AC-4: trigger button on PolicyDetailPage */}
        <button
          type="button"
          className="btn-primary"
          aria-label={`Activate policy ${policyName}`}
        >
          Activate
        </button>
      </AlertDialog.Trigger>

      {/* Radix Portal renders outside DOM tree — avoids stacking-context issues */}
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 bg-black/40" />
        <AlertDialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
            bg-white rounded-lg shadow-xl p-6 w-[420px] max-w-[90vw]"
          aria-describedby="activate-dialog-desc"
        >
          <AlertDialog.Title className="text-lg font-semibold mb-2">
            Activate Policy
          </AlertDialog.Title>
          <AlertDialog.Description
            id="activate-dialog-desc"
            className="text-sm text-gray-600 mb-6"
          >
            Activating <strong>{policyName}</strong> will immediately replace the
            currently enforced policy in OPA. This action is recorded in the audit
            trail. Continue?
          </AlertDialog.Description>

          <div className="flex justify-end gap-3">
            {/* AC-4: Cancel — no mutation */}
            <AlertDialog.Cancel asChild>
              <button type="button" className="btn-secondary" disabled={isPending}>
                Cancel
              </button>
            </AlertDialog.Cancel>

            {/* AC-4: Confirm — fires activate mutation */}
            <AlertDialog.Action asChild>
              <button
                type="button"
                className="btn-danger"
                onClick={handleConfirm}
                disabled={isPending}
                aria-busy={isPending}
              >
                {isPending ? "Activating…" : "Activate"}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
```

---

### `RollbackDropdown`

```tsx
// frontend/admin-portal/src/components/policies/RollbackDropdown.tsx
import * as Select           from "@radix-ui/react-select";
import { ChevronDownIcon }   from "@radix-ui/react-icons";
import { useRollbackPolicy } from "../../services/policyService";
import type { PolicyListItem } from "../../services/policyService";

interface Props { policy: PolicyListItem; }

export function RollbackDropdown({ policy }: Props) {
  const { mutate: rollback, isPending } = useRollbackPolicy();

  // AC-5: list all non-active versions as rollback candidates
  const rollbackVersions = policy.versions.filter(
    (v) => v.status !== "active"
  );

  if (rollbackVersions.length === 0) return null;

  const handleSelect = (version: string) =>
    rollback({ policyId: policy.id, version });

  return (
    <Select.Root onValueChange={handleSelect} disabled={isPending}>
      <Select.Trigger
        className="btn-secondary flex items-center gap-1"
        aria-label="Rollback to a previous policy version"
      >
        <Select.Value placeholder="Rollback to…" />
        <Select.Icon>
          <ChevronDownIcon aria-hidden="true" />
        </Select.Icon>
      </Select.Trigger>

      <Select.Portal>
        <Select.Content
          className="bg-white border rounded-lg shadow-lg py-1 z-50"
          position="popper"
          sideOffset={4}
        >
          <Select.Viewport>
            {rollbackVersions.map((v) => (
              <Select.Item
                key={v.id}
                value={v.version}
                className="flex items-center px-3 py-2 text-sm cursor-pointer
                  hover:bg-gray-100 focus:bg-gray-100 outline-none"
                aria-label={`Rollback to version ${v.version} (${v.status})`}
              >
                <Select.ItemText>
                  v{v.version} — {v.status}
                </Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
```

## Acceptance Criteria

- [ ] Clicking "Activate" opens the `AlertDialog` with the policy name and audit notice in the description (AC-4)
- [ ] Clicking "Cancel" in the dialog closes it without calling any API (AC-4)
- [ ] Clicking "Activate" in the dialog fires `POST /v1/policies/{id}/activate`; on success the dialog closes and the policy list is re-fetched (AC-4)
- [ ] While the activate mutation is in flight, both dialog buttons are `disabled` and "Activate" shows "Activating…" with `aria-busy="true"` (AC-4)
- [ ] `RollbackDropdown` is not rendered when there are no non-active versions (AC-5)
- [ ] Selecting a version from the dropdown fires `POST /v1/policies/{id}/rollback?version=N` (AC-5)
- [ ] On successful rollback, both `POLICY_KEYS.all` and `POLICY_KEYS.detail(policyId)` query caches are invalidated (AC-5)
- [ ] `AlertDialog` traps focus inside while open; `Escape` key closes it (Radix UI handles natively — AC-7)
- [ ] `RollbackDropdown` trigger has `aria-label="Rollback to a previous policy version"` (AC-7)

## Dependencies

- TASK-US040-01 — `policyService.ts` (extended with new mutations)
- TASK-US040-02 — `PolicyDetailPage` renders both components
- US-033 TASK-US033-04 — `POST /v1/policies/{id}/activate` and `POST /v1/policies/{id}/rollback` endpoints exist

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] Tests: dialog opens/closes, activate mutation fires on confirm, rollback mutation fires on select, no rollback candidates → dropdown not rendered
