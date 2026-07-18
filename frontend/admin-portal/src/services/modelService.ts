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
    onSuccess: () => qc.invalidateQueries({ queryKey: MODEL_KEYS.all }),
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
