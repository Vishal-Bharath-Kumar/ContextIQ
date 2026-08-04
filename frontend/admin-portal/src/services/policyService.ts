import axios from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

export interface PolicyVersion {
  id: string;
  policy_group: string;
  version: string;
  status: "draft" | "active" | "superseded" | "rolled_back";
  author: string;
  description: string;
  rego_body?: string;
  activated_at: string | null; // ISO-8601
  created_at: string;
}

export interface PolicyListItem {
  id: string;
  name: string;
  active_version: string | null;
  versions: PolicyVersion[];
  latest_author: string;
  activated_at: string | null;
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

export const POLICY_KEYS = {
  all: ["policies"] as const,
  detail: (id: string) => ["policies", id] as const,
};

export function usePolicies(): UseQueryResult<PolicyListItem[], Error> {
  return useQuery({
    queryKey: POLICY_KEYS.all,
    queryFn: () =>
      api.get<PolicyListItem[]>("/v1/policies").then((r) => r.data),
  });
}

export function useCreatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      name: string;
      description: string;
      version: string;
      rego_body: string;
    }) => api.post<PolicyVersion>("/v1/policies", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: POLICY_KEYS.all }),
  });
}

export interface RegoValidationResult {
  valid: boolean;
  errors: string[];
}

/** Validate Rego against OPA without persisting. */
export function useValidateRego() {
  return useMutation({
    mutationFn: (regoBody: string) =>
      api
        .post<RegoValidationResult>("/v1/policies/validate", { rego_body: regoBody })
        .then((r) => r.data),
  });
}

export function usePolicyDetail(policyId: string | undefined): UseQueryResult<PolicyListItem, Error> {
  return useQuery({
    queryKey: POLICY_KEYS.detail(policyId ?? ""),
    queryFn: () =>
      api.get<PolicyListItem>(`/v1/policies/${policyId}`).then((r) => r.data),
    enabled: Boolean(policyId),
  });
}

export function useActivatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policyId: string) =>
      api.post(`/v1/policies/${policyId}/activate`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: POLICY_KEYS.all }),
  });
}

export function useDeactivatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policyId: string) =>
      api.post<PolicyVersion>(`/v1/policies/${policyId}/deactivate`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: POLICY_KEYS.all }),
  });
}

export function useUpdatePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      policyId,
      description,
      rego_body,
    }: {
      policyId: string;
      description?: string;
      rego_body?: string;
    }) =>
      api
        .put<PolicyVersion>(`/v1/policies/${policyId}`, {
          description,
          rego_body,
        })
        .then((r) => r.data),
    onSuccess: (_data, { policyId }) => {
      qc.invalidateQueries({ queryKey: POLICY_KEYS.all });
      qc.invalidateQueries({ queryKey: POLICY_KEYS.detail(policyId) });
    },
  });
}

export function useDeletePolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policyId: string) =>
      api.delete(`/v1/policies/${policyId}`).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: POLICY_KEYS.all });
    },
  });
}

export interface PolicyPreviewResult {
  evaluated_count: number;
  allow_count: number;
  deny_count: number;
  allow_pct: number;
  deny_pct: number;
  affected_request_ids: string[];
}

export function usePreviewPolicy() {
  return useMutation({
    mutationFn: ({
      policyId,
      regoBody,
    }: {
      policyId: string;
      regoBody: string;
    }) =>
      api
        .post<PolicyPreviewResult>(`/v1/policies/${policyId}/preview`, {
          rego_body: regoBody,
        })
        .then((r) => r.data),
  });
}

// ── AC-6: Audit trail ────────────────────────────────────────────────────────

export interface AuditLogEntry {
  id: string;
  event_type: string;
  actor_user_id: string;
  detail: string | null;
  created_at: string; // ISO-8601
}

export function usePolicyAuditTrail(policyId: string | undefined): UseQueryResult<AuditLogEntry[], Error> {
  return useQuery({
    queryKey: [...POLICY_KEYS.detail(policyId ?? ""), "audit"],
    queryFn: () =>
      api
        .get<AuditLogEntry[]>(`/v1/policies/${policyId}/audit`)
        .then((r) => r.data),
    enabled: Boolean(policyId),
  });
}
