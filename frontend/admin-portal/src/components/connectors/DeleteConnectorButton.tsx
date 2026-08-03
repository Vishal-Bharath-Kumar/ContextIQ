import { useState } from "react";
import { TrashIcon } from "@radix-ui/react-icons";
import { useDeleteConnector } from "../../services/connectorService";

interface Props {
  connectorId: string;
  connectorName: string;
}

export function DeleteConnectorButton({ connectorId, connectorName }: Props) {
  const { mutate: deleteConnector, isPending } = useDeleteConnector();
  const [error, setError] = useState<string | null>(null);

  const handleDelete = () => {
    const confirmed = window.confirm(
      `Delete connector "${connectorName}"? This permanently removes its sync history and cannot be undone.`
    );
    if (!confirmed) return;

    setError(null);
    deleteConnector(connectorId, {
      onError: () => setError("Failed to delete. Please try again."),
    });
  };

  return (
    <div className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={handleDelete}
        disabled={isPending}
        aria-busy={isPending}
        aria-label={`Delete connector ${connectorName}`}
        className="inline-flex items-center gap-1 px-3 py-1 rounded text-xs font-medium border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1"
      >
        <TrashIcon aria-hidden="true" />
        {isPending ? "Deleting…" : "Delete"}
      </button>
      {error && (
        <span role="alert" className="text-xs font-medium text-red-600">
          {error}
        </span>
      )}
    </div>
  );
}
