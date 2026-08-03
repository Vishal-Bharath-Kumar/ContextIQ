import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { useState } from "react";
import { TrashIcon } from "@radix-ui/react-icons";
import { useDeletePolicy } from "../../services/policyService";

interface Props {
  policyId: string;
  policyVersion: string;
  policyStatus: "draft" | "active" | "superseded" | "rolled_back";
  onDeleteSuccess?: () => void;
}

export function DeletePolicyDialog({ 
  policyId, 
  policyVersion, 
  policyStatus,
  onDeleteSuccess 
}: Props) {
  const [open, setOpen] = useState(false);
  const { mutate: deletePolicy, isPending, error } = useDeletePolicy();

  // Only allow deletion of DRAFT or SUPERSEDED policies
  const canDelete = policyStatus === "draft" || policyStatus === "superseded";

  const handleConfirm = () => {
    deletePolicy(policyId, {
      onSuccess: () => {
        setOpen(false);
        onDeleteSuccess?.();
      },
    });
  };

  if (!canDelete) {
    return (
      <button
        type="button"
        className="text-gray-400 cursor-not-allowed text-xs"
        disabled
        title="Only DRAFT or SUPERSEDED policies can be deleted"
      >
        Delete
      </button>
    );
  }

  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        <button
          type="button"
          className="text-red-600 hover:text-red-800 hover:underline text-xs flex items-center gap-1"
          aria-label={`Delete policy version ${policyVersion}`}
        >
          <TrashIcon className="w-3 h-3" aria-hidden="true" />
          Delete
        </button>
      </AlertDialog.Trigger>

      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 bg-black/40 z-40" />
        <AlertDialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
            bg-white rounded-lg shadow-xl p-6 w-[420px] max-w-[90vw] z-50"
          aria-describedby="delete-dialog-desc"
        >
          <AlertDialog.Title className="text-lg font-semibold mb-2 text-red-600">
            Delete Policy Version
          </AlertDialog.Title>
          <AlertDialog.Description
            id="delete-dialog-desc"
            className="text-sm text-gray-600 mb-6"
          >
            Are you sure you want to delete version <strong>{policyVersion}</strong>?
            This action cannot be undone.
          </AlertDialog.Description>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
              {error instanceof Error ? error.message : "Failed to delete policy"}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <button type="button" className="btn-secondary" disabled={isPending}>
                Cancel
              </button>
            </AlertDialog.Cancel>

            <AlertDialog.Action asChild>
              <button
                type="button"
                className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg
                  transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={handleConfirm}
                disabled={isPending}
                aria-busy={isPending}
              >
                {isPending ? "Deleting…" : "Delete"}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
