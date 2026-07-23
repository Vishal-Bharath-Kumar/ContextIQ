import { useState } from "react";
import { ReloadIcon } from "@radix-ui/react-icons";
import { useTriggerSync } from "../../services/connectorService";

interface Props {
  connectorId: string;
}

export function SyncNowButton({ connectorId }: Props) {
  const { mutate: triggerSync, isPending } = useTriggerSync();
  const [message, setMessage] = useState<string | null>(null);

  const handleSync = () => {
    setMessage(null);
    triggerSync(connectorId, {
      onSuccess: () => setMessage("Sync started"),
      onError: () => setMessage("Failed to start sync"),
    });
  };

  return (
    <div className="inline-flex flex-col gap-1">
      <button
        type="button"
        onClick={handleSync}
        disabled={isPending}
        aria-busy={isPending}
        aria-label="Sync connector now"
        className="inline-flex items-center gap-1 px-3 py-1 rounded text-xs font-medium border border-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
      >
        <ReloadIcon aria-hidden="true" />
        {isPending ? "Starting…" : "Sync Now"}
      </button>
      {message && (
        <span role="status" aria-live="polite" className="text-xs font-medium text-gray-500">
          {message}
        </span>
      )}
    </div>
  );
}
