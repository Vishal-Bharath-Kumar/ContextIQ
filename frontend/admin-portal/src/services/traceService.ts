import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import type {
  TraceDetailResponse,
  TraceListResponse,
  TraceSearchParams,
} from "../pages/traces/trace.models";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
});

api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) {
    const { token } = JSON.parse(raw) as { token: string };
    cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

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

      const { data } = await api.get<TraceListResponse>(`/v1/traces?${p.toString()}`);
      return data;
    },
  });
}

/** AC-2 / AC-3: Fetch full trace detail for a single request. */
export function useTraceDetail(id: string) {
  return useQuery({
    queryKey: TRACE_KEYS.detail(id),
    queryFn:  async () => {
      const { data } = await api.get<TraceDetailResponse>(`/v1/traces/${encodeURIComponent(id)}`);
      return data;
    },
    enabled: !!id,
  });
}

function filenameFromDisposition(value: string | null | undefined, fallbackId: string): string {
  if (!value) {
    return `contextiq-trace-${fallbackId}.json`;
  }
  const match = /filename="?([^";]+)"?/i.exec(value);
  return match?.[1] ?? `contextiq-trace-${fallbackId}.json`;
}

/** AC-6: Download full execution trace with the same authenticated API client as the rest of the portal. */
export async function downloadTraceExport(id: string): Promise<void> {
  const response = await api.get<Blob>(`/v1/traces/${encodeURIComponent(id)}/export`, {
    responseType: "blob",
  });

  const filename = filenameFromDisposition(response.headers["content-disposition"], id);
  const objectUrl = window.URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(objectUrl);
}
