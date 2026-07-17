import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import type {
  TraceDetailResponse,
  TraceListResponse,
  TraceSearchParams,
} from "../pages/traces/trace.models";

export const TRACE_KEYS = {
  list:   (params: TraceSearchParams) => ["traces", params] as const,
  detail: (id: string)                => ["traces", id, "detail"] as const,
};

export function useTraces(params: TraceSearchParams) {
  return useQuery({
    queryKey: TRACE_KEYS.list(params),
    queryFn:  async () => {
      const p = new URLSearchParams();
      p.set("limit",  params.limit.toString());
      p.set("offset", params.offset.toString());
      if (params.user_id)        p.set("user_id",        params.user_id);
      if (params.intent)         p.set("intent",         params.intent);
      if (params.model_selected) p.set("model_selected", params.model_selected);
      if (params.governance_blocked !== undefined) {
        p.set("governance_blocked", String(params.governance_blocked));
      }
      if (params.from) p.set("from", params.from);
      if (params.to)   p.set("to",   params.to);

      const { data } = await axios.get<TraceListResponse>(`/v1/traces?${p.toString()}`);
      return data;
    },
  });
}

/** AC-2 / AC-3: Fetch full trace detail for a single request. */
export function useTraceDetail(id: string) {
  return useQuery({
    queryKey: TRACE_KEYS.detail(id),
    queryFn:  async () => {
      const { data } = await axios.get<TraceDetailResponse>(`/v1/traces/${encodeURIComponent(id)}`);
      return data;
    },
    enabled: !!id,
  });
}

/** AC-6: Return the export URL for programmatic anchor-download. */
export function traceExportUrl(id: string): string {
  return `/v1/traces/${encodeURIComponent(id)}/export`;
}
