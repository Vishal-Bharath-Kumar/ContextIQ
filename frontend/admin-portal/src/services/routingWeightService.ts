import axios from "axios";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

export interface RoutingWeightEntry {
  intent_type: string;
  quality_weight: number;
  cost_weight: number;
  latency_weight: number;
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
});

api.interceptors.request.use((cfg) => {
  const raw = sessionStorage.getItem("admin_user");
  if (raw) {
    cfg.headers.Authorization = `Bearer ${JSON.parse(raw).token}`;
  }
  return cfg;
});

export const WEIGHT_KEYS = { all: ["routing-weights"] as const };

export function useRoutingWeights(): UseQueryResult<RoutingWeightEntry[], Error> {
  return useQuery({
    queryKey: WEIGHT_KEYS.all,
    queryFn: () =>
      api
        .get<RoutingWeightEntry[]>("/v1/routing/weights")
        .then((r) => r.data),
  });
}

export function useUpdateRoutingWeights() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      intentType,
      weights,
    }: {
      intentType: string;
      weights: {
        quality_weight: number;
        cost_weight: number;
        latency_weight: number;
      };
    }) =>
      api
        .put<RoutingWeightEntry>(`/v1/routing/weights/${intentType}`, weights)
        .then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: WEIGHT_KEYS.all }),
  });
}
