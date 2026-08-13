/**
 * TypeScript interfaces that mirror the backend API DTOs for execution traces.
 * Kept in sync with GET /v1/traces (TASK-US035-02) response schema.
 */

export interface TraceListItem {
  request_id:         string;
  user_id:            string;
  timestamp:          string;  // ISO-8601
  intent:             string;
  model_selected:     string | null;
  governance_blocked: boolean;
  opa_denied_count:   number;
  object_key:         string;
}

export interface TraceListResponse {
  items:  TraceListItem[];
  total:  number;
  limit:  number;
  offset: number;
}

export interface TraceSearchParams {
  user_id?:            string;
  intent?:             string;
  model_selected?:     string;
  governance_blocked?: boolean;
  from?:               string;  // ISO-8601
  to?:                 string;  // ISO-8601
  limit:               number;
  offset:              number;
}

// ── Detail-view types (TASK-US035-04) ─────────────────────────────────────────

export interface RetrievedChunkSummary {
  chunk_id:             string;
  source_id:            string;
  relevance_score:      number;
  classification_label: string;
  redacted:             boolean;
  opa_denied:           boolean;
}

export interface CompressionDelta {
  tokens_before: number;
  tokens_after:  number;
  chunks_before: number;
  chunks_after:  number;
  reduction_pct: number;
}

export interface GovernanceDecisionSummary {
  findings_count:     number;
  redacted_count:     number;
  opa_denied_count:   number;
  opa_bundle_version: string;
  governance_blocked: boolean;
}

export interface TimelineStep {
  step_number: number;
  node:        string;
  eval_ms:     number | null;
  metadata:    Record<string, unknown>;
}

export interface TraceDetailResponse {
  request_id:            string;
  user_id:               string;
  timestamp:             string;  // ISO-8601
  latency_ms:            number | null;
  // AC-3 fields
  intent_classification: string;
  intent_confidence:     number | null;
  retrieved_sources:     RetrievedChunkSummary[];
  compression_delta:     CompressionDelta | null;
  governance_decisions:  GovernanceDecisionSummary;
  model_selected:        string | null;
  prompt_tokens:         number | null;
  completion_tokens:     number | null;
  response_summary:      string | null;
  // AC-2
  timeline:              TimelineStep[];
}
