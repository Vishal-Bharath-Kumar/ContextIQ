import type { ModelCapability } from "../../services/modelService";

export function CapabilityTagList({
  capabilities,
}: {
  capabilities: ModelCapability[];
}) {
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Capabilities">
      {capabilities.map((c) => (
        <li
          key={c}
          className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-xs font-mono"
        >
          {c}
        </li>
      ))}
    </ul>
  );
}
