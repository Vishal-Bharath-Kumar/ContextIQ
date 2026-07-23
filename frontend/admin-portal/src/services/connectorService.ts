import axios from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface ConnectorSummary {
  id: string;
  // Nullable: connectors created before the name column was added have no name.
  name: string | null;
  connector_type: string;
  status: "active" | "inactive" | "syncing" | "error";
  last_sync_at: string | null; // ISO-8601
  document_count: number;
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
});

// Inject Bearer token for every request
api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) {
    const { token } = JSON.parse(raw) as { token: string };
    cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

export const CONNECTOR_KEYS = {
  all: ["connectors"] as const,
  detail: (id: string) => ["connectors", id] as const,
};

export function useConnectors() {
  return useQuery({
    queryKey: CONNECTOR_KEYS.all,
    queryFn: () =>
      api
        .get<ConnectorSummary[]>("/v1/knowledge-sources")
        .then((r) => r.data),
  });
}

export function useToggleConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.patch(`/v1/knowledge-sources/${id}/status`, {
        active: enabled,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTOR_KEYS.all }),
  });
}

export function useCreateConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: import("../schemas/connectorWizard").ConnectorCreatePayload) =>
      api.post("/v1/knowledge-sources", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTOR_KEYS.all }),
  });
}

export function useDeleteConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/v1/knowledge-sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTOR_KEYS.all }),
  });
}

export interface SyncTriggerResult {
  job_id: string;
  message: string;
}

export function useTriggerSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api
        .post<SyncTriggerResult>(`/v1/knowledge-sources/${id}/sync`)
        .then((r) => r.data),
    // Sync runs in the background; refresh the list so status/last_sync_at/
    // document_count pick up the "syncing" -> "active" transition.
    onSuccess: () => qc.invalidateQueries({ queryKey: CONNECTOR_KEYS.all }),
  });
}

export interface HealthCheckResult {
  ok: boolean;
  latency_ms: number;
  detail: string | null;
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (connectorId: string) =>
      api
        .post<HealthCheckResult>(`/v1/knowledge-sources/${connectorId}/health-check`)
        .then((r) => r.data),
  });
}
