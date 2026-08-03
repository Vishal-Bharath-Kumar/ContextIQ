import type { AuditLogEntry } from "../../services/auditLogService";

interface Props {
  entries: AuditLogEntry[];
}

/**
 * Renders audit log entries with all AC-1 fields visible:
 * action, resource, actor, IP address, and timestamp.
 */
export function AuditLogTable({ entries }: Props) {
  if (entries.length === 0) {
    return (
      <p role="status" className="text-secondary py-8 text-center">
        No audit log entries found.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table
        className="min-w-full divide-y divide-border text-sm"
        aria-label="Audit log entries"
      >
        <thead className="bg-surface-subtle">
          <tr>
            <th scope="col" className="px-4 py-3 text-left font-medium">Timestamp</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Action</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Resource</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Resource ID</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Actor</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">IP Address</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface">
          {entries.map((entry) => (
            <tr key={entry.id} className="hover:bg-surface-subtle transition-colors">
              <td className="px-4 py-3 whitespace-nowrap font-mono text-xs">
                {new Date(entry.timestamp).toLocaleString()}
              </td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center rounded-full bg-accent-subtle px-2 py-0.5 text-xs font-medium">
                  {entry.action}
                </span>
              </td>
              <td className="px-4 py-3 text-secondary">{entry.resource_type}</td>
              <td className="px-4 py-3 font-mono text-xs truncate max-w-[12rem]" title={entry.resource_id}>
                {entry.resource_id}
              </td>
              <td className="px-4 py-3 font-mono text-xs truncate max-w-[12rem]" title={entry.actor_user_id}>
                {entry.actor_user_id}
              </td>
              <td className="px-4 py-3 font-mono text-xs">{entry.ip_address}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
