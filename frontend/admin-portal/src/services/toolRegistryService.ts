import axios from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export type ToolStatus = "active" | "inactive";

export interface ToolDefinition {
  id: string;
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  status: ToolStatus;
  version: string;
  created_at: string;
  updated_at: string;
}

export interface ToolCreatePayload {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  version: string;
}

export interface ToolUpdatePayload {
  description?: string;
  inputSchema?: Record<string, unknown>;
  status?: ToolStatus;
  version?: string;
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

export const TOOL_KEYS = {
  all: ["tools"] as const,
  detail: (name: string) => ["tools", name] as const,
};

export function useTools(status?: ToolStatus) {
  return useQuery({
    queryKey: [...TOOL_KEYS.all, status ?? "all"],
    queryFn: () =>
      api
        .get<ToolDefinition[]>("/v1/tools", { params: status ? { status } : undefined })
        .then((r) => r.data),
  });
}

export function useTool(name?: string) {
  return useQuery({
    queryKey: name ? TOOL_KEYS.detail(name) : ["tools", "detail-disabled"],
    queryFn: () => api.get<ToolDefinition>(`/v1/tools/${name}`).then((r) => r.data),
    enabled: Boolean(name),
  });
}

export function useCreateTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ToolCreatePayload) =>
      api.post<ToolDefinition>("/v1/tools", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: TOOL_KEYS.all }),
  });
}

export function useUpdateTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: ToolUpdatePayload }) =>
      api.patch<ToolDefinition>(`/v1/tools/${name}`, payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: TOOL_KEYS.all }),
  });
}

export function useToggleToolStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, status }: { name: string; status: ToolStatus }) =>
      api.patch<ToolDefinition>(`/v1/tools/${name}`, { status }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: TOOL_KEYS.all }),
  });
}

export function useDeleteTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.delete<ToolDefinition>(`/v1/tools/${name}`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: TOOL_KEYS.all }),
  });
}
