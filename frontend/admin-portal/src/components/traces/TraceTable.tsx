import { Link } from "react-router-dom";
import type { TraceListItem } from "../../pages/traces/trace.models";

interface Props {
  items: TraceListItem[];
}

export function TraceTable({ items }: Props) {
  if (items.length === 0) {
    return (
      <p role="status" className="text-secondary py-8 text-center">
        No execution traces found.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table
        className="min-w-full divide-y divide-border text-sm"
        aria-label="Execution trace results"
      >
        <thead className="bg-surface-subtle">
          <tr>
            <th scope="col" className="px-4 py-3 text-left font-medium">Timestamp</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">User</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Intent</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Model</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Governance</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">Denied chunks</th>
            <th scope="col" className="px-4 py-3 text-left font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-surface">
          {items.map((item) => (
            <tr
              key={item.request_id}
              className="hover:bg-surface-subtle transition-colors cursor-pointer"
            >
              <td className="px-4 py-3 whitespace-nowrap font-mono text-xs">
                {new Date(item.timestamp).toLocaleString()}
              </td>
              <td
                className="px-4 py-3 font-mono text-xs truncate max-w-[12rem]"
                title={item.user_id}
              >
                {item.user_id}
              </td>
              <td className="px-4 py-3">{item.intent}</td>
              <td className="px-4 py-3 text-secondary">
                {item.model_selected ?? "—"}
              </td>
              <td className="px-4 py-3">
                <span
                  className={
                    item.governance_blocked
                      ? "inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"
                      : "inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
                  }
                >
                  {item.governance_blocked ? "Blocked" : "Allowed"}
                </span>
              </td>
              <td className="px-4 py-3 text-center">{item.opa_denied_count}</td>
              <td className="px-4 py-3">
                <Link
                  to={`/traces/${item.request_id}`}
                  className="text-primary hover:underline text-sm font-medium"
                  aria-label={`View trace detail for request ${item.request_id}`}
                >
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
