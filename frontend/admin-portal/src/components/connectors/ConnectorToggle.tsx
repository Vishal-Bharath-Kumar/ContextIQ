import * as Switch from "@radix-ui/react-switch";
import { useToggleConnector } from "../../services/connectorService";

interface Props {
  connectorId: string;
  enabled: boolean;
}

export function ConnectorToggle({ connectorId, enabled }: Props) {
  const { mutate: toggle, isPending } = useToggleConnector();

  const handleChange = (checked: boolean) => {
    toggle({ id: connectorId, enabled: checked });
  };

  const label = enabled ? "Disable connector" : "Enable connector";

  return (
    <Switch.Root
      checked={enabled}
      onCheckedChange={handleChange}
      disabled={isPending}
      aria-label={label}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
        ${enabled ? "bg-blue-600" : "bg-gray-300"}
        ${isPending ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
        focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-1`}
    >
      <Switch.Thumb
        className="block h-4 w-4 rounded-full bg-white shadow
          transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5"
      />
    </Switch.Root>
  );
}
