import { useState } from "react";
import { useTestConnection } from "../../services/connectorService";
import type { HealthCheckResult } from "../../services/connectorService";

interface Props {
  connectorId: string;
}

type ResultState = HealthCheckResult | null;

export function TestConnectionButton({ connectorId }: Props) {
  const { mutate: test, isPending } = useTestConnection();
  const [result, setResult] = useState<ResultState>(null);

  const handleTest = () => {
    setResult(null);
    test(connectorId, {
      onSuccess: (data) => setResult(data),
      onError: () => setResult({ ok: false, latency_ms: 0, detail: "Request failed" }),
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
        className="inline-flex items-center px-3 py-1 rounded text-xs font-medium border border-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1"
      >
        {isPending ? "Testing…" : "Test Connection"}
      </button>

      {result !== null && (
        <span
          role="status"
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
