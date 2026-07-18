import * as Select from "@radix-ui/react-select";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { useRollbackPolicy } from "../../services/policyService";
import type { PolicyListItem } from "../../services/policyService";

interface Props {
  policy: PolicyListItem;
}

export function RollbackDropdown({ policy }: Props) {
  const { mutate: rollback, isPending } = useRollbackPolicy();

  const rollbackVersions = policy.versions.filter((v) => v.status !== "active");

  if (rollbackVersions.length === 0) return null;

  const handleSelect = (version: string) =>
    rollback({ policyId: policy.id, version });

  return (
    <Select.Root onValueChange={handleSelect} disabled={isPending}>
      <Select.Trigger
        className="btn-secondary flex items-center gap-1"
        aria-label="Rollback to a previous policy version"
      >
        <Select.Value placeholder="Rollback to…" />
        <Select.Icon>
          <ChevronDownIcon aria-hidden="true" />
        </Select.Icon>
      </Select.Trigger>

      <Select.Portal>
        <Select.Content
          className="bg-white border rounded-lg shadow-lg py-1 z-50"
          position="popper"
          sideOffset={4}
        >
          <Select.Viewport>
            {rollbackVersions.map((v) => (
              <Select.Item
                key={v.id}
                value={v.version}
                className="flex items-center px-3 py-2 text-sm cursor-pointer
                  hover:bg-gray-100 focus:bg-gray-100 outline-none"
                aria-label={`Rollback to version ${v.version} (${v.status})`}
              >
                <Select.ItemText>
                  v{v.version} — {v.status}
                </Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}
