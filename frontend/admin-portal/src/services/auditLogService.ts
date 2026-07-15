import { useInfiniteQuery } from "@tanstack/react-query";
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

interface AuditLogPage {
  items:       AuditLogEntry[];
  next_cursor: string | null;
}

export const AUDIT_KEYS = {
  list: (filters: AuditLogFilters) => ["audit-log", filters] as const,
};

export function useAuditLog(filters: AuditLogFilters) {
  return useInfiniteQuery({
    queryKey:  AUDIT_KEYS.list(filters),
    queryFn:   async ({ pageParam }) => {
      const params = new URLSearchParams();
      if (filters.user)          params.set("user",          filters.user);
      if (filters.action)        params.set("action",        filters.action);
      if (filters.resource_type) params.set("resource_type", filters.resource_type);
      if (filters.resource_id)   params.set("resource_id",   filters.resource_id);
      if (filters.date_from)     params.set("date_from",     filters.date_from);
      if (filters.date_to)       params.set("date_to",       filters.date_to);
      if (pageParam)             params.set("cursor",        pageParam);
      const { data } = await axios.get<AuditLogPage>(`/v1/audit-log?${params.toString()}`);
      return data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 60_000,   // 1 min — audit log entries are immutable and change slowly
  });
}
