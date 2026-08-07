import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import axios from "axios";

export interface AuditLogEntry {
  id:            string;
  action:        string;
  resource_type: string;
  resource_id:   string;
  actor_user_id: string;
  ip_address:    string;
  before_state:  Record<string, unknown> | null;
  after_state:   Record<string, unknown> | null;
  timestamp:     string;
  row_hash:      string;
}

export interface AuditLogFilters {
  user?:          string;
  action?:        string;
  resource_type?: string;
  resource_id?:   string;
  date_from?:     string;   // ISO 8601
  date_to?:       string;
}

export interface AuditLogSearchParams extends AuditLogFilters {
  cursor?: string;
  limit?:  number;
}

interface AuditLogPage {
  items:       AuditLogEntry[];
  next_cursor: string | null;
}

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

export const AUDIT_KEYS = {
  list: (params: AuditLogSearchParams) => ["audit-log", params] as const,
};

export function useAuditLog(params: AuditLogSearchParams): UseQueryResult<AuditLogPage, Error> {
  return useQuery({
    queryKey: AUDIT_KEYS.list(params),
    queryFn:  async () => {
      const queryParams = new URLSearchParams();
      if (params.user)          queryParams.set("user",          params.user);
      if (params.action)        queryParams.set("action",        params.action);
      if (params.resource_type) queryParams.set("resource_type", params.resource_type);
      if (params.resource_id)   queryParams.set("resource_id",   params.resource_id);
      if (params.date_from)     queryParams.set("date_from",     params.date_from);
      if (params.date_to)       queryParams.set("date_to",       params.date_to);
      if (params.cursor)        queryParams.set("cursor",        params.cursor);
      queryParams.set("limit", String(params.limit ?? 10));
      const { data } = await api.get<AuditLogPage>(`/v1/audit-log?${queryParams.toString()}`);
      return data;
    },
    staleTime: 60_000,   // 1 min — audit log entries are immutable and change slowly
  });
}
