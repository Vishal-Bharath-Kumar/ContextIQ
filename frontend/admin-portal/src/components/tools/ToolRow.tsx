import * as AlertDialog from "@radix-ui/react-alert-dialog";
import * as Switch from "@radix-ui/react-switch";
import { useState } from "react";
import { Link } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import { Pencil1Icon, TrashIcon } from "@radix-ui/react-icons";

import type { ToolDefinition } from "../../services/toolRegistryService";
import { useDeleteTool, useToggleToolStatus } from "../../services/toolRegistryService";
import { ToolStatusBadge } from "./ToolStatusBadge";

interface Props {
  tool: ToolDefinition;
}

export function ToolRow({ tool }: Props) {
  const { mutate: toggle, isPending: isToggling } = useToggleToolStatus();
  const { mutate: deleteTool, isPending: isDeleting } = useDeleteTool();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const isActive = tool.status === "active";

  return (
    <tr className="border-t border-border/60 transition-colors hover:bg-white/40">
      <td className="px-4 py-3">
        <p className="font-medium text-slate-800">{tool.name}</p>
        <p className="max-w-xs truncate text-xs text-secondary">{tool.description}</p>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-secondary">{tool.version}</td>
      <td className="px-4 py-3">
        <ToolStatusBadge status={tool.status} />
      </td>
      <td className="px-4 py-3 text-xs text-secondary">
        {formatDistanceToNow(new Date(tool.updated_at), { addSuffix: true })}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <Switch.Root
            checked={isActive}
            onCheckedChange={(checked) =>
              toggle({ name: tool.name, status: checked ? "active" : "inactive" })
            }
            disabled={isToggling}
            aria-label={isActive ? `Deactivate ${tool.name}` : `Activate ${tool.name}`}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
              ${isActive ? "bg-primary-600" : "bg-slate-300"}
              ${isToggling ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
              focus:outline-none focus:ring-2 focus:ring-primary-400 focus:ring-offset-1`}
          >
            <Switch.Thumb className="block h-4 w-4 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0.5" />
          </Switch.Root>

          <Link
            to={`/tools/${encodeURIComponent(tool.name)}/edit`}
            className="btn-ghost !px-2 !py-1"
            aria-label={`Edit ${tool.name}`}
          >
            <Pencil1Icon aria-hidden="true" />
          </Link>

          <AlertDialog.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
            <AlertDialog.Trigger asChild>
              <button
                type="button"
                className="btn-ghost !px-2 !py-1 text-red-600 hover:bg-red-50/60"
                aria-label={`Delete ${tool.name}`}
              >
                <TrashIcon aria-hidden="true" />
              </button>
            </AlertDialog.Trigger>

            <AlertDialog.Portal>
              <AlertDialog.Overlay className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm" />
              <AlertDialog.Content
                className="glass-panel fixed left-1/2 top-1/2 z-50 w-[420px] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 p-6"
                aria-describedby="delete-tool-desc"
              >
                <AlertDialog.Title className="mb-2 text-lg font-semibold text-slate-900">
                  Deactivate Tool
                </AlertDialog.Title>
                <AlertDialog.Description id="delete-tool-desc" className="mb-6 text-sm text-secondary">
                  This will soft-delete <strong>{tool.name}</strong> by marking it inactive. Agents
                  will no longer be able to invoke this tool. This action is recorded in the audit
                  trail.
                </AlertDialog.Description>

                <div className="flex justify-end gap-3">
                  <AlertDialog.Cancel asChild>
                    <button type="button" className="btn-secondary" disabled={isDeleting}>
                      Cancel
                    </button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action asChild>
                    <button
                      type="button"
                      className="btn-danger"
                      onClick={() => deleteTool(tool.name, { onSuccess: () => setConfirmOpen(false) })}
                      disabled={isDeleting}
                      aria-busy={isDeleting}
                    >
                      {isDeleting ? "Removing…" : "Deactivate"}
                    </button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Portal>
          </AlertDialog.Root>
        </div>
      </td>
    </tr>
  );
}
