import { useState } from "react";
import { RequireAuditor } from "../guards";
import { AuditLogFilterBar } from "../components/audit/AuditLogFilterBar";
import { AuditLogTable } from "../components/audit/AuditLogTable";
import { useAuditLog } from "../services/auditLogService";
import type { AuditLogFilters } from "../services/auditLogService";

const PAGE_SIZE = 10;

export function AuditLogPage() {
  const [filters, setFilters] = useState<AuditLogFilters>({});
  const [pageCursors, setPageCursors] = useState<Array<string | undefined>>([undefined]);
  const currentCursor = pageCursors[pageCursors.length - 1];
  const {
    data,
    isLoading,
    isFetching,
  } = useAuditLog({ ...filters, cursor: currentCursor, limit: PAGE_SIZE });

  const currentPage = pageCursors.length;
  const hasPreviousPage = pageCursors.length > 1;
  const hasNextPage = !!data?.next_cursor;
  const isPaging = isFetching && !isLoading;

  function handleFilter(nextFilters: AuditLogFilters): void {
    setFilters(nextFilters);
    setPageCursors([undefined]);
  }

  function handlePreviousPage(): void {
    setPageCursors((current) => current.slice(0, -1));
  }

  function handleNextPage(): void {
    if (!data?.next_cursor) {
      return;
    }

    setPageCursors((current) => [...current, data.next_cursor ?? undefined]);
  }

  const entries = data?.items ?? [];

  return (
    // AC-5: AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN role required
    <RequireAuditor>
      <main aria-labelledby="audit-log-heading" className="page-layout">
        <h1 id="audit-log-heading" className="page-title">
          Audit Log
        </h1>

        <AuditLogFilterBar onFilter={handleFilter} />

        {isLoading ? (
          <p role="status" aria-live="polite">
            Loading audit log…
          </p>
        ) : (
          <AuditLogTable entries={entries} />
        )}

        {(entries.length > 0 || hasPreviousPage || hasNextPage) && (
          <nav
            className="mt-4 flex items-center justify-between gap-3"
            aria-label="Audit log pagination"
          >
            <p className="text-sm text-secondary">
              Page {currentPage} · {PAGE_SIZE} entries per page
            </p>
            <div className="flex gap-2">
              <button
                onClick={handlePreviousPage}
                disabled={!hasPreviousPage || isPaging}
                className="btn-secondary"
                aria-label="Previous page"
              >
                Previous
              </button>
              <button
                onClick={handleNextPage}
                disabled={!hasNextPage || isPaging}
                className="btn-secondary"
                aria-label="Next page"
              >
                {isPaging ? "Loading…" : "Next"}
              </button>
            </div>
          </nav>
        )}
      </main>
    </RequireAuditor>
  );
}
