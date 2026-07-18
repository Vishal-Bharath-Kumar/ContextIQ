import * as Switch from "@radix-ui/react-switch";
import { CapabilityTagList } from "./CapabilityTagList";
import { LatencyBadge } from "./LatencyBadge";
import { useToggleModelStatus } from "../../services/modelService";
import type { ModelDefinition } from "../../services/modelService";

interface Props {
  model: ModelDefinition;
}

export function ModelRow({ model }: Props) {
  const { mutate: toggle, isPending } = useToggleModelStatus();

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="px-4 py-2 font-mono text-xs">{model.model_id}</td>
      <td className="px-4 py-2">{model.provider}</td>
      <td className="px-4 py-2">{model.context_window.toLocaleString()}</td>
      <td className="px-4 py-2">${model.cost_per_1k_tokens.toFixed(4)}</td>
      <td className="px-4 py-2">
        <LatencyBadge tier={model.latency_tier} />
      </td>
      <td className="px-4 py-2">
        <CapabilityTagList capabilities={model.capabilities} />
      </td>
      <td className="px-4 py-2">
        <Switch.Root
          checked={model.is_active}
          onCheckedChange={(checked) =>
            toggle({ id: model.id, isActive: checked })
          }
          disabled={isPending}
          aria-label={
            model.is_active
              ? `Deactivate ${model.model_id}`
              : `Activate ${model.model_id}`
          }
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
            ${model.is_active ? "bg-blue-600" : "bg-gray-300"}
            ${isPending ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
            focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1`}
        >
          <Switch.Thumb className="block h-4 w-4 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5" />
        </Switch.Root>
      </td>
    </tr>
  );
}
