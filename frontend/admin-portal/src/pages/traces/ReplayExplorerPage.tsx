import { useState } from "react";
import { TraceFilterBar } from "../../components/traces/TraceFilterBar";
import type { TraceFilters } from "../../components/traces/TraceFilterBar";
import { TraceTable } from "../../components/traces/TraceTable";
import { useTraces } from "../../services/traceService";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 25;

export function ReplayExplorerPage() {
  const [filters,  setFilters]  = useState<TraceFilters>({});
  const [page,     setPage]     = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const { data, isLoading, isError, error } = useTraces({
    ...filters,
    limit:  pageSize,
    offset: page * pageSize,
  });

  const items      = data?.items ?? [];
  const total      = data?.total ?? 0;
  const totalPages = Math.ceil(total / pageSize);

  function handleFilter(newFilters: TraceFilters): void {
    setFilters(newFilters);
    setPage(0);
  }

  return (
    <main aria-labelledby="replay-explorer-heading" className="page-layout">
      <h1 id="replay-explorer-heading" className="page-title">
        Replay Explorer
      </h1>

      {/* AC-1: search filters with 400 ms debounce (inside TraceFilterBar) */}
      <TraceFilterBar onFilter={handleFilter} />

      {isLoading ? (
        <p role="status" aria-live="polite">
          Loading traces…
        </p>
      ) : isError ? (
        <p role="alert" className="text-danger py-8 text-center">
          {error instanceof Error
            ? `Could not load execution traces: ${error.message}`
            : "Could not load execution traces."}
        </p>
      ) : (
        <TraceTable items={items} />
      )}

      {/* Pagination — only shown when there are results */}
      {total > 0 && (
        <nav
          className="flex items-center justify-between mt-4"
          aria-label="Trace list pagination"
        >
          <div className="flex items-center gap-2 text-sm text-secondary">
            <span>Rows per page:</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(0);
              }}
              aria-label="Rows per page"
              className="input"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
            <span>
              {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} of {total}
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => p - 1)}
              disabled={page === 0}
              className="btn-secondary"
              aria-label="Previous page"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page >= totalPages - 1}
              className="btn-secondary"
              aria-label="Next page"
            >
              Next
            </button>
          </div>
        </nav>
      )}
    </main>
  );
}
