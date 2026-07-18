import * as Collapsible from "@radix-ui/react-collapsible";
import { ChevronDownIcon, ChevronUpIcon } from "@radix-ui/react-icons";
import { useState } from "react";

import {
  usePreviewPolicy,
  type PolicyPreviewResult,
} from "../../services/policyService";

interface Props {
  policyId: string;
  regoBody: string;
}

export function PreviewImpactPanel({ policyId, regoBody }: Props) {
  const [open, setOpen] = useState(false);
  const { mutate: preview, isPending, data: result } = usePreviewPolicy();

  const handlePreview = () => {
    setOpen(true);
    preview({ policyId, regoBody });
  };

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen}>
      <Collapsible.Trigger asChild>
        <button
          type="button"
          className="btn-secondary flex items-center gap-1"
          onClick={handlePreview}
          aria-expanded={open}
          aria-controls="preview-impact-content"
          aria-label="Preview impact of this policy on recent requests"
        >
          Preview Impact
          {open ? (
            <ChevronUpIcon aria-hidden="true" />
          ) : (
            <ChevronDownIcon aria-hidden="true" />
          )}
        </button>
      </Collapsible.Trigger>

      <Collapsible.Content id="preview-impact-content">
        <div
          className="mt-3 p-4 border rounded-lg bg-gray-50"
          aria-live="polite"
          role="region"
          aria-label="Preview impact results"
        >
          {isPending && (
            <p role="status">Simulating against last 100 requests…</p>
          )}

          {result && !isPending && <PreviewStats result={result} />}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

function PreviewStats({ result }: { result: PolicyPreviewResult }) {
  return (
    <div>
      <p className="text-sm mb-3">
        Evaluated <strong>{result.evaluated_count}</strong> recent requests:
      </p>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="bg-green-50 rounded p-3 text-center">
          <div className="text-2xl font-bold text-green-700">
            {result.allow_count}
          </div>
          <div className="text-xs text-green-600">
            Would Allow ({result.allow_pct}%)
          </div>
        </div>
        <div className="bg-red-50 rounded p-3 text-center">
          <div className="text-2xl font-bold text-red-700">
            {result.deny_count}
          </div>
          <div className="text-xs text-red-600">
            Would Deny ({result.deny_pct}%)
          </div>
        </div>
      </div>

      {result.affected_request_ids.length > 0 && (
        <details>
          <summary className="text-sm font-medium text-gray-700 cursor-pointer mb-1">
            Affected request IDs ({result.affected_request_ids.length})
          </summary>
          <ul className="text-xs font-mono space-y-0.5 max-h-40 overflow-y-auto">
            {result.affected_request_ids.map((id) => (
              <li key={id} className="text-gray-500">
                {id}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
