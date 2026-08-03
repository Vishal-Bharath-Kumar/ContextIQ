import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { useState } from "react";
import { useDeactivatePolicy } from "../../services/policyService";

interface Props {
  policyId: string;
  policyName: string;
}

export function DeactivatePolicyDialog({ policyId, policyName }: Props) {
  const [open, setOpen] = useState(false);
  const { mutate: deactivate, isPending } = useDeactivatePolicy();

  const handleConfirm = () =>
    deactivate(policyId, { onSuccess: () => setOpen(false) });

  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        <button
          type="button"
          className="btn-secondary"
          aria-label={`Deactivate policy ${policyName}`}
        >
          Deactivate
        </button>
      </AlertDialog.Trigger>

      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 bg-black/40" />
        <AlertDialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
            bg-white rounded-lg shadow-xl p-6 w-[420px] max-w-[90vw]"
          aria-describedby="deactivate-dialog-desc"
        >
          <AlertDialog.Title className="text-lg font-semibold mb-2">
            Deactivate Policy
          </AlertDialog.Title>
          <AlertDialog.Description
            id="deactivate-dialog-desc"
            className="text-sm text-gray-600 mb-6"
          >
            Deactivating <strong>{policyName}</strong> will immediately remove it
            from OPA and stop enforcing this policy. This action is recorded in the
            audit trail. Continue?
          </AlertDialog.Description>

          <div className="flex justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <button type="button" className="btn-secondary" disabled={isPending}>
                Cancel
              </button>
            </AlertDialog.Cancel>

            <AlertDialog.Action asChild>
              <button
                type="button"
                className="btn-danger"
                onClick={handleConfirm}
                disabled={isPending}
                aria-busy={isPending}
              >
                {isPending ? "Deactivating…" : "Deactivate"}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
