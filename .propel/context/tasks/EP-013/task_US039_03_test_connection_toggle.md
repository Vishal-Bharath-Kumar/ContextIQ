# TASK-US039-03 — Test Connection Inline Result and Enable/Disable Toggle

## Metadata

| Field | Value |
|---|---|
| ID | TASK-US039-03 |
| User Story | US-039 |
| Epic | EP-013 — Administration Portal |
| Layer | Frontend |
| Priority | P0 |
| Points | 1 |
| Status | Draft |

## Description

Implement the two interactive controls on each connector row: `TestConnectionButton` (AC-3) which calls `POST /v1/knowledge-sources/{id}/health-check` and renders the result inline without a page reload; and `ConnectorToggle` (AC-4) which calls `PATCH /v1/knowledge-sources/{id}/status` and applies the change within 30 s via optimistic UI + React Query invalidation. Both components are keyboard-accessible (AC-7).

## Implementation Details

**Technology:** React 18, TypeScript, TanStack Query v5 (`useMutation`), Radix UI `Switch`, Radix UI `Tooltip`

**File locations:**
- `frontend/admin-portal/src/components/connectors/TestConnectionButton.tsx`
- `frontend/admin-portal/src/components/connectors/ConnectorToggle.tsx`
- `frontend/admin-portal/src/services/connectorService.ts` — extend with `useTestConnection` + `useToggleConnector`

---

### `useTestConnection` mutation

```ts
// frontend/admin-portal/src/services/connectorService.ts  (extend)
export interface HealthCheckResult {
  ok:           boolean;
  latency_ms:   number;
  detail:       string | null;   // error message when ok=false
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (connectorId: string) =>
      api
        .post<HealthCheckResult>(`/v1/knowledge-sources/${connectorId}/health-check`)
        .then((r) => r.data),
    // No cache invalidation — health check is a read-only side-effect
  });
}
```

---

### `TestConnectionButton`

```tsx
// frontend/admin-portal/src/components/connectors/TestConnectionButton.tsx
import { useState }          from "react";
import { useTestConnection } from "../../services/connectorService";
import type { HealthCheckResult } from "../../services/connectorService";

interface Props { connectorId: string; }

type ResultState = HealthCheckResult | null;

export function TestConnectionButton({ connectorId }: Props) {
  const { mutate: test, isPending } = useTestConnection();
  const [result, setResult]         = useState<ResultState>(null);

  const handleTest = () => {
    setResult(null);
    test(connectorId, {
      onSuccess: (data) => setResult(data),
      onError:   ()     => setResult({ ok: false, latency_ms: 0, detail: "Request failed" }),
    });
  };

  return (
    <div className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={handleTest}
        disabled={isPending}
        aria-busy={isPending}
        aria-label="Test connector connection"
        className="btn-secondary text-xs"
      >
        {isPending ? "Testing…" : "Test Connection"}
      </button>

      {/* Inline result — rendered adjacent to button; no modal (AC-3) */}
      {result !== null && (
        <span
          role="status"        // live region for screen reader announcement (AC-7)
          aria-live="polite"
          className={`text-xs font-medium ${result.ok ? "text-green-700" : "text-red-600"}`}
        >
          {result.ok
            ? `OK (${result.latency_ms} ms)`
            : `Failed: ${result.detail ?? "Unknown error"}`}
        </span>
      )}
    </div>
  );
}
```

---

### `ConnectorToggle`

```tsx
// frontend/admin-portal/src/components/connectors/ConnectorToggle.tsx
import * as Switch          from "@radix-ui/react-switch";
import { useToggleConnector } from "../../services/connectorService";

interface Props {
  connectorId: string;
  enabled:     boolean;
}

export function ConnectorToggle({ connectorId, enabled }: Props) {
  const { mutate: toggle, isPending } = useToggleConnector();

  const handleChange = (checked: boolean) => {
    // Optimistic UI: React Query's onMutate could be used for instant feedback,
    // but invalidateQueries after success is sufficient — the 30 s SLA (AC-4)
    // is met by the backend status change propagating within one polling cycle.
    toggle({ id: connectorId, enabled: checked });
  };

  const label = enabled ? "Disable connector" : "Enable connector";

  return (
    <Switch.Root
      checked={enabled}
      onCheckedChange={handleChange}
      disabled={isPending}
      aria-label={label}       // Screen reader announces the action, not the state (AC-7)
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
        ${enabled ? "bg-blue-600" : "bg-gray-300"}
        ${isPending ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
    >
      <Switch.Thumb
        className="block h-4 w-4 rounded-full bg-white shadow
          transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5"
      />
    </Switch.Root>
  );
}
```

---

### `useToggleConnector` mutation (already defined in TASK-US039-01 — no duplicate)

The mutation is defined in `connectorService.ts` in TASK-US039-01:

```ts
// Already implemented — no changes needed:
// export function useToggleConnector() { ... PATCH /v1/knowledge-sources/{id}/status ... }
```

## Acceptance Criteria

- [ ] Clicking "Test Connection" while a request is in-flight shows "Testing…" and disables the button; `aria-busy="true"` is set (AC-3)
- [ ] On success, inline result shows "OK (N ms)" in green without any page reload (AC-3)
- [ ] On failure, inline result shows "Failed: {detail}" in red (AC-3)
- [ ] `role="status"` with `aria-live="polite"` ensures the result is announced to screen readers (AC-7)
- [ ] `ConnectorToggle` fires `PATCH /v1/knowledge-sources/{id}/status` on change (AC-4)
- [ ] After a successful toggle, `useConnectors` query is invalidated and the list re-fetches — status change visible within one polling cycle (<30 s) (AC-4)
- [ ] Toggle renders `aria-label="Enable connector"` when connector is inactive, `"Disable connector"` when active (AC-7)
- [ ] Toggle is fully keyboard-operable via `Space` / `Enter` (Radix UI `Switch.Root` handles this natively) (AC-7)

## Dependencies

- TASK-US039-01 — `ConnectorRow` imports both components; `useToggleConnector` is defined in `connectorService.ts`
- TASK-US039-04 — `POST /v1/knowledge-sources/{id}/health-check` backend route must exist

## Definition of Done

- [ ] `pnpm build` succeeds with no TypeScript errors
- [ ] React Testing Library tests: success result rendered, failure message rendered, toggle fires mutation
