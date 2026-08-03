import { formatDistanceToNow } from "date-fns";
import { ConnectorStatusBadge } from "./ConnectorStatusBadge";
import { ConnectorToggle } from "./ConnectorToggle";
import { TestConnectionButton } from "./TestConnectionButton";
import { SyncNowButton } from "./SyncNowButton";
import { DeleteConnectorButton } from "./DeleteConnectorButton";
import type { ConnectorSummary } from "../../services/connectorService";

interface Props {
  connector: ConnectorSummary;
}

export function ConnectorRow({ connector }: Props) {
  const lastSync = connector.last_sync_at
    ? formatDistanceToNow(new Date(connector.last_sync_at), { addSuffix: true })
    : "Never";
  // Fallback for connectors created before the name column existed.
  const displayName = connector.name?.trim() || connector.connector_type;

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="p-3 font-medium">{displayName}</td>
      <td className="p-3 capitalize">{connector.connector_type}</td>
      <td className="p-3">
        <ConnectorStatusBadge status={connector.status} />
      </td>
      <td className="p-3 text-gray-500">{lastSync}</td>
      <td className="p-3">{connector.document_count.toLocaleString()}</td>
      <td className="p-3 flex gap-2">
        <TestConnectionButton connectorId={connector.id} />
        <SyncNowButton connectorId={connector.id} />
        <ConnectorToggle
          connectorId={connector.id}
          enabled={connector.status === "active"}
        />
        <DeleteConnectorButton connectorId={connector.id} connectorName={displayName} />
      </td>
    </tr>
  );
}
