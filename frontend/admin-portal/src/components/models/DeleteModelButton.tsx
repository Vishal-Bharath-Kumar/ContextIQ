import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { useState } from "react";
import { TrashIcon } from "@radix-ui/react-icons";
import { useDeleteModel } from "../../services/modelService";

interface Props {
  modelId: string;
  modelName: string;
  provider: string;
}

export function DeleteModelButton({ modelId, modelName, provider }: Props) {
  const [open, setOpen] = useState(false);
  const [deleteFromOllama, setDeleteFromOllama] = useState(false);
  const { mutate: deleteModel, isPending, error } = useDeleteModel();

  const isOllama = provider.toLowerCase() === "ollama";

  const handleConfirm = () => {
    deleteModel(
      { id: modelId, deleteFromOllama },
      {
        onSuccess: () => {
          setOpen(false);
          setDeleteFromOllama(false);
        },
      }
    );
  };

  return (
    <AlertDialog.Root open={open} onOpenChange={setOpen}>
      <AlertDialog.Trigger asChild>
        <button
          type="button"
          className="text-red-600 hover:text-red-800 text-sm px-2 py-1 rounded hover:bg-red-50 transition-colors"
          aria-label={`Delete model ${modelName}`}
          title="Delete model"
        >
          <TrashIcon className="w-4 h-4" aria-hidden="true" />
        </button>
      </AlertDialog.Trigger>

      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 bg-black/40 z-40" />
        <AlertDialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
            bg-white rounded-lg shadow-xl p-6 w-[480px] max-w-[90vw] z-50"
          aria-describedby="delete-dialog-desc"
        >
          <AlertDialog.Title className="text-lg font-semibold mb-2 text-red-600">
            Delete Model
          </AlertDialog.Title>
          <AlertDialog.Description
            id="delete-dialog-desc"
            className="text-sm text-gray-600 mb-4"
          >
            Are you sure you want to delete <strong>{modelName}</strong>?
            This will remove the model from the registry.
          </AlertDialog.Description>

          {isOllama && (
            <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deleteFromOllama}
                  onChange={(e) => setDeleteFromOllama(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-amber-600 text-amber-600 
                    focus:ring-amber-500 cursor-pointer"
                />
                <div>
                  <div className="text-sm font-medium text-amber-900 mb-1">
                    Also delete from Ollama
                  </div>
                  <div className="text-xs text-amber-700">
                    This will permanently remove the model files from your Ollama installation.
                    Leave unchecked to only remove from ContextIQ registry.
                  </div>
                </div>
              </label>
            </div>
          )}

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
              {error instanceof Error ? error.message : "Failed to delete model"}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <AlertDialog.Cancel asChild>
              <button
                type="button"
                className="px-4 py-2 text-sm border rounded hover:bg-gray-50"
                disabled={isPending}
              >
                Cancel
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded hover:bg-red-700
                  disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isPending ? "Deleting..." : "Delete Model"}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
