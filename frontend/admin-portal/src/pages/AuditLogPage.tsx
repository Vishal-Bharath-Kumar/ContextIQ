import { useState } from "react";
import { RequireAuditor } from "../guards";
import { AuditLogFilterBar } from "../components/audit/AuditLogFilterBar";
import { AuditLogTable } from "../components/audit/AuditLogTable";
import { useAuditLog } from "../services/auditLogService";
import type { AuditLogFilters } from "../services/auditLogService";

export function AuditLogPage() {
  const [filters, setFilters] = useState<AuditLogFilters>({});
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useAuditLog(filters);

  const allEntries = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    // AC-5: AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN role required
    <RequireAuditor>
      <main aria-labelledby="audit-log-heading" className="page-layout">
        <h1 id="audit-log-heading" className="page-title">
          Audit Log
        </h1>

        <AuditLogFilterBar onFilter={setFilters} />

        {isLoading ? (
          <p role="status" aria-live="polite">
            Loading audit log…
          </p>
        ) : (
          <AuditLogTable entries={allEntries} />
        )}

        {hasNextPage && (
          <button
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
            className="btn-secondary mt-4"
            aria-label="Load next page of audit log entries"
          >
            {isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        )}
      </main>
    </RequireAuditor>
  );
}
