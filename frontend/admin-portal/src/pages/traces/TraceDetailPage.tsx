import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { downloadTraceExport, useTraceDetail } from "../../services/traceService";
import type { RetrievedChunkSummary, TimelineStep } from "./trace.models";

// ── Small presentational helpers ─────────────────────────────────────────────

function StatusBadge({ redacted, opaDenied }: { redacted: boolean; opaDenied: boolean }) {
  if (redacted) {
    return (
      <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
        Redacted
      </span>
    );
  }
  if (opaDenied) {
    return (
      <span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
        OPA Denied
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
      OK
    </span>
  );
}

/** Converts a 0–1 relevance score into a percentage string for the progress bar. */
function relevancePct(score: number): number {
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

// ── Section panels ────────────────────────────────────────────────────────────

function SectionPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details open className="border border-border rounded-lg overflow-hidden">
      <summary className="cursor-pointer select-none px-4 py-3 bg-surface-subtle font-medium text-sm">
        {title}
      </summary>
      <div className="px-4 py-4 bg-surface text-sm">{children}</div>
    </details>
  );
}

function MetaRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex gap-4 py-1">
      <dt className="w-40 shrink-0 font-medium text-secondary">{label}</dt>
      <dd className="flex-1">{value}</dd>
    </div>
  );
}

// ── Timeline ──────────────────────────────────────────────────────────────────

function TimelineSection({ steps }: { steps: TimelineStep[] }) {
  return (
    <SectionPanel title={`Pipeline Timeline (${steps.length} steps)`}>
      <ol className="space-y-2" aria-label="Pipeline execution steps">
        {steps.map((step) => (
          <li key={step.step_number} className="flex items-center gap-3">
            <span
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-white text-xs font-bold"
              aria-hidden="true"
            >
              {step.step_number}
            </span>
            <span className="font-mono text-xs flex-1">{step.node}</span>
            {step.eval_ms !== null && (
              <span className="text-xs text-secondary">{step.eval_ms.toFixed(1)} ms</span>
            )}
          </li>
        ))}
      </ol>
    </SectionPanel>
  );
}

// ── Retrieved sources ─────────────────────────────────────────────────────────

function SourcesSection({ sources }: { sources: RetrievedChunkSummary[] }) {
  return (
    <SectionPanel title={`Retrieved Sources (${sources.length})`}>
      <div className="overflow-x-auto">
        <table
          className="min-w-full divide-y divide-border text-xs"
          aria-label="Retrieved source chunks"
        >
          <thead className="bg-surface-subtle">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">Chunk ID</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Source</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Classification</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Relevance</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border bg-surface">
            {sources.map((src) => (
              <tr key={src.chunk_id}>
                <td className="px-3 py-2 font-mono" title={src.chunk_id}>
                  {src.chunk_id.slice(0, 8)}…
                </td>
                <td className="px-3 py-2 font-mono" title={src.source_id}>
                  {src.source_id.slice(0, 8)}…
                </td>
                <td className="px-3 py-2">{src.classification_label}</td>
                <td className="px-3 py-2 w-32">
                  <div
                    role="progressbar"
                    aria-valuenow={relevancePct(src.relevance_score)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`Relevance score ${src.relevance_score.toFixed(3)}`}
                    title={`${src.relevance_score.toFixed(3)}`}
                    className="h-2 rounded-full bg-border overflow-hidden"
                  >
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${relevancePct(src.relevance_score)}%` }}
                    />
                  </div>
                </td>
                <td className="px-3 py-2">
                  <StatusBadge redacted={src.redacted} opaDenied={src.opa_denied} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionPanel>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function TraceDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const { data: trace, isLoading, isError } = useTraceDetail(id);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  /** AC-6: Authenticated export through the same API client used by the rest of the portal. */
  async function handleExport() {
    if (!id || isExporting) {
      return;
    }

    setExportError(null);
    setIsExporting(true);
    try {
      await downloadTraceExport(id);
    } catch {
      setExportError("Failed to export trace. Please try again.");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <main aria-labelledby="trace-detail-heading" className="page-layout">
      {/* Back navigation */}
      <Link
        to="/traces"
        className="inline-flex items-center gap-1 text-sm text-primary hover:underline mb-4"
        aria-label="Back to Replay Explorer"
      >
        ← Back to list
      </Link>

      {isLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading trace…
        </p>
      )}

      {isError && (
        <p role="alert" className="text-red-600 py-4">
          Failed to load trace. Please try again.
        </p>
      )}

      {trace && (
        <div className="space-y-4">
          {/* Header card */}
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1
                  id="trace-detail-heading"
                  className="text-lg font-semibold font-mono break-all"
                >
                  Trace {trace.request_id}
                </h1>
                <p className="text-sm text-secondary mt-0.5">
                  {new Date(trace.timestamp).toLocaleString(undefined, { dateStyle: "long", timeStyle: "medium" })}
                </p>
              </div>

              {/* AC-6: Export button */}
              <button
                onClick={handleExport}
                disabled={isExporting}
                className="btn-secondary shrink-0"
                aria-label="Export trace as JSON file"
              >
                {isExporting ? "Exporting…" : "↓ Export JSON"}
              </button>
            </div>

            {exportError && (
              <p role="alert" className="mt-3 text-sm text-red-600">
                {exportError}
              </p>
            )}

            <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
              <MetaRow label="User" value={<span className="font-mono">{trace.user_id}</span>} />
              <MetaRow
                label="Latency"
                value={trace.latency_ms !== null ? `${trace.latency_ms.toLocaleString()} ms` : "—"}
              />
            </dl>
          </div>

          {/* AC-3: Intent classification */}
          <SectionPanel title="Intent Classification">
            <p className="font-mono text-sm">{trace.intent_classification}</p>
          </SectionPanel>

          {/* AC-2 + AC-3: Pipeline timeline */}
          <TimelineSection steps={trace.timeline} />

          {/* AC-3: Retrieved sources */}
          <SourcesSection sources={trace.retrieved_sources} />

          {/* AC-3: Compression delta — conditional */}
          {trace.compression_delta && (
            <SectionPanel title="Compression Delta">
              <dl className="space-y-1">
                <MetaRow label="Tokens before" value={trace.compression_delta.tokens_before.toLocaleString()} />
                <MetaRow label="Tokens after"  value={trace.compression_delta.tokens_after.toLocaleString()} />
                <MetaRow label="Reduction"     value={`${trace.compression_delta.reduction_pct}%`} />
                <MetaRow label="Chunks before" value={trace.compression_delta.chunks_before} />
                <MetaRow label="Chunks after"  value={trace.compression_delta.chunks_after} />
              </dl>
            </SectionPanel>
          )}

          {/* AC-3: Governance decisions */}
          <SectionPanel title="Governance Decisions">
            <dl className="space-y-1">
              <MetaRow
                label="Blocked"
                value={
                  <span
                    className={
                      trace.governance_decisions.governance_blocked
                        ? "inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700"
                        : "inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
                    }
                  >
                    {trace.governance_decisions.governance_blocked ? "Yes" : "No"}
                  </span>
                }
              />
              <MetaRow label="Findings"       value={trace.governance_decisions.findings_count} />
              <MetaRow label="Redacted"        value={trace.governance_decisions.redacted_count} />
              <MetaRow label="OPA denied"      value={trace.governance_decisions.opa_denied_count} />
              <MetaRow label="Bundle version"  value={trace.governance_decisions.opa_bundle_version} />
            </dl>
          </SectionPanel>

          {/* AC-3: Model routing */}
          <SectionPanel title="Model Routing">
            <dl className="space-y-1">
              <MetaRow label="Model"             value={trace.model_selected ?? "—"} />
              <MetaRow label="Prompt tokens"     value={trace.prompt_tokens     !== null ? trace.prompt_tokens.toLocaleString()     : "—"} />
              <MetaRow label="Completion tokens" value={trace.completion_tokens !== null ? trace.completion_tokens.toLocaleString() : "—"} />
            </dl>
          </SectionPanel>

          {/* AC-3: Response summary — conditional */}
          {trace.response_summary && (
            <SectionPanel title="Response Summary">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {trace.response_summary}
              </p>
            </SectionPanel>
          )}
        </div>
      )}
    </main>
  );
}
