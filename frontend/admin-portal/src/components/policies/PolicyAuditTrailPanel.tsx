import { format } from "date-fns";

import { usePolicyAuditTrail } from "../../services/policyService";

interface Props {
  policyId: string;
}

const EVENT_LABEL: Record<string, string> = {
  created: "Policy created",
  activated: "Policy activated",
  rollback: "Policy rolled back",
  deactivated: "Policy deactivated",
  validated: "Rego validated",
};

export function PolicyAuditTrailPanel({ policyId }: Props) {
  const { data: entries, isLoading } = usePolicyAuditTrail(policyId);

  if (isLoading) {
    return (
      <p role="status" aria-live="polite" className="text-sm text-gray-400">
        Loading audit trail…
      </p>
    );
  }

  if (!entries || entries.length === 0) {
    return (
      <p className="text-sm text-gray-400">No audit events recorded yet.</p>
    );
  }

  return (
    <section aria-label="Policy audit trail">
      <h3 className="text-sm font-semibold mb-2">Audit Trail</h3>
      <ol className="space-y-2 text-sm">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="flex items-start gap-3 border-l-2 border-gray-200 pl-3"
          >
            <div className="min-w-0">
              <span className="font-medium">
                {EVENT_LABEL[entry.event_type] ?? entry.event_type}
              </span>
              {entry.detail && (
                <span className="text-gray-500"> — {entry.detail}</span>
              )}
              <div className="text-xs text-gray-400 mt-0.5">
                {/* AC-6: actor user ID and formatted timestamp */}
                by <span className="font-mono">{entry.actor_user_id}</span>
                {" · "}
                <time dateTime={entry.created_at}>
                  {format(new Date(entry.created_at), "yyyy-MM-dd HH:mm 'UTC'")}
                </time>
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
