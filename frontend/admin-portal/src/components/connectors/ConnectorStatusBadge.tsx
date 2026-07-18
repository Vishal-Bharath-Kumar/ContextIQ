type ConnectorStatus = "active" | "inactive" | "syncing" | "error";

interface Props {
  status: ConnectorStatus;
}

const BADGE: Record<ConnectorStatus, { label: string; className: string }> = {
  active: { label: "Active", className: "badge-green" },
  inactive: { label: "Inactive", className: "badge-grey" },
  syncing: { label: "Syncing", className: "badge-blue" },
  error: { label: "Error", className: "badge-red" },
};

export function ConnectorStatusBadge({ status }: Props) {
  const { label, className } = BADGE[status];
  return (
    // aria-label carries semantic status for screen readers (WCAG 2.1 AA, AC-7)
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}
      aria-label={`Connector status: ${label}`}
    >
      {label}
    </span>
  );
}
