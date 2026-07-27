import axios from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export type LatencyTier = "fast" | "medium" | "slow";
export type ModelCapability =
  | "chat"
  | "completion"
  | "embedding"
  | "code"
  | "summarization"
  | "vision"
  | "function_call";

export interface ModelDefinition {
  id: string;
  model_id: string; // LiteLLM format, e.g. "anthropic/claude-3-haiku"
  provider: string;
  context_window: number;
  cost_per_1k_tokens: number;
  latency_tier: LatencyTier;
  capabilities: ModelCapability[];
  is_active: boolean;
  created_at: string;
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

export const MODEL_KEYS = {
  all: ["models"] as const,
  detail: (id: string) => ["models", id] as const,
};

export function useModels() {
  return useQuery({
    queryKey: MODEL_KEYS.all,
    queryFn: () =>
      api.get<ModelDefinition[]>("/v1/models").then((r) => r.data),
  });
}

export function useToggleModelStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      api
        .patch(`/v1/models/${id}/status`, { is_active: isActive })
        .then((r) => r.data as ModelDefinition),
    onSuccess: async () => {
      // Force immediate refetch by using refetchQueries instead of invalidateQueries
      await qc.refetchQueries({ queryKey: MODEL_KEYS.all, type: 'active' });
    },
  });
}

export function useCreateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: import("../schemas/addModelSchema").AddModelFields) =>
      api.post<ModelDefinition>("/v1/models", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: MODEL_KEYS.all }),
  });
}

export interface DailyCostPoint {
  date: string;
  cost_usd: number;
}

export interface ModelCostSummary {
  model_id: string;
  total_cost_usd: number;
  daily_series: DailyCostPoint[];
  total_tokens: number;
}

export function useCostAnalytics(days = 30) {
  return useQuery({
    queryKey: ["model-cost-analytics", days],
    queryFn: () =>
      api
        .get<ModelCostSummary[]>(`/v1/models/cost-analytics?days=${days}`)
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
}

export interface OllamaModel {
  name: string;
  size: number;
  digest: string;
  modified_at: string;
}

export interface ModelInstallationResponse {
  model_id: string;
  provider_type: string;
  status: string;
  message: string;
  credentials_stored: boolean;
}

export function useOllamaModels() {
  return useQuery({
    queryKey: ["ollama-models"],
    queryFn: () =>
      api.get<OllamaModel[]>("/v1/models/ollama").then((r) => r.data),
    staleTime: 30 * 1000, // 30 seconds
  });
}

export function useInstallModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: import("../schemas/installModelSchema").InstallModelFields) =>
      api.post<ModelInstallationResponse>("/v1/models/install", payload).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MODEL_KEYS.all });
      qc.invalidateQueries({ queryKey: ["ollama-models"] });
    },
  });
}

export function usePullOllamaModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { model_name: string }) =>
      api.post("/v1/models/ollama/pull", payload).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ollama-models"] });
    },
  });
}

export function useDeleteModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, deleteFromOllama }: { id: string; deleteFromOllama?: boolean }) => {
      console.log('[DELETE] Attempting to delete model:', id, 'deleteFromOllama:', deleteFromOllama);
      console.log('[DELETE] Auth token exists:', !!sessionStorage.getItem("admin_user"));
      try {
        const response = await api.delete(`/v1/models/${id}`, { params: { delete_from_ollama: deleteFromOllama ?? false } });
        console.log('[DELETE] Success:', response.data);
        return response.data;
      } catch (error: any) {
        console.error('[DELETE] Error:', error.response?.status, error.response?.data);
        throw error;
      }
    },
    onSuccess: async () => {
      console.log('[DELETE] onSuccess - refetching queries');
      // Force immediate refetch
      await qc.refetchQueries({ queryKey: MODEL_KEYS.all, type: 'active' });
      await qc.refetchQueries({ queryKey: ["ollama-models"], type: 'active' });
    },
    onError: (error: any) => {
      console.error('[DELETE] onError:', error.response?.status, error.response?.data);
    },
  });
}
