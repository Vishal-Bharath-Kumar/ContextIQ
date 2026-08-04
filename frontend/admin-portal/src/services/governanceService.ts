import axios from "axios";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient, UseQueryResult } from "@tanstack/react-query";

// ------------------------------------------------------------------ //
// Types                                                               //
// ------------------------------------------------------------------ //

export interface ComplianceStandard {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  requirementCount: number;
}

export interface ComplianceSettings {
  standards: ComplianceStandard[];
}

export interface RolePermissions {
  role: string;
  displayName: string;
  permissions: string[];
  maxClassification: string;
  color: string;
}

export interface RBACSettings {
  roles: RolePermissions[];
}

export interface PatternConfig {
  id: string;
  name: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  enabled: boolean;
  matchCount?: number;
}

export interface PatternCategory {
  id: string;
  name: string;
  description: string;
  patterns: PatternConfig[];
}

export interface PatternDetectionSettings {
  categories: PatternCategory[];
}

export interface SeverityWeight {
  severity: string;
  weight: number;
  description: string;
}

export interface RiskScoringSettings {
  severityWeights: SeverityWeight[];
  violationPenalty: number;
}

export interface GovernanceSettings {
  compliance: ComplianceSettings;
  rbac: RBACSettings;
  patterns: PatternDetectionSettings;
  riskScoring: RiskScoringSettings;
}

// ------------------------------------------------------------------ //
// API Client                                                          //
// ------------------------------------------------------------------ //

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

// ------------------------------------------------------------------ //
// Query Keys                                                          //
// ------------------------------------------------------------------ //

export const GOVERNANCE_KEYS = {
  all: ["governance"] as const,
  settings: () => ["governance", "settings"] as const,
  compliance: () => ["governance", "compliance"] as const,
  rbac: () => ["governance", "rbac"] as const,
  patterns: () => ["governance", "patterns"] as const,
  riskScoring: () => ["governance", "risk-scoring"] as const,
};

// ------------------------------------------------------------------ //
// Hooks                                                               //
// ------------------------------------------------------------------ //

/**
 * Get complete governance settings
 */
export function useGovernanceSettings(): UseQueryResult<GovernanceSettings, Error> {
  return useQuery({
    queryKey: GOVERNANCE_KEYS.settings(),
    queryFn: () =>
      api.get<GovernanceSettings>("/v1/governance/settings").then((r) => r.data),
  });
}

/**
 * Update compliance standards configuration
 */
export function useUpdateComplianceSettings() {
  const qc: QueryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: ComplianceSettings) =>
      api.put<ComplianceSettings>("/v1/governance/compliance", settings).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData<GovernanceSettings | undefined>(
        GOVERNANCE_KEYS.settings(),
        (current: GovernanceSettings | undefined) => current ? { ...current, compliance: data } : current
      );
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.settings() });
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.compliance() });
    },
  });
}

/**
 * Update RBAC role permissions
 */
export function useUpdateRBACSettings() {
  const qc: QueryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: RBACSettings) =>
      api.put<RBACSettings>("/v1/governance/rbac", settings).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData<GovernanceSettings | undefined>(
        GOVERNANCE_KEYS.settings(),
        (current: GovernanceSettings | undefined) => current ? { ...current, rbac: data } : current
      );
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.settings() });
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.rbac() });
    },
  });
}

/**
 * Update pattern detection configuration
 */
export function useUpdatePatternSettings() {
  const qc: QueryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: PatternDetectionSettings) =>
      api.put<PatternDetectionSettings>("/v1/governance/patterns", settings).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData<GovernanceSettings | undefined>(
        GOVERNANCE_KEYS.settings(),
        (current: GovernanceSettings | undefined) => current ? { ...current, patterns: data } : current
      );
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.settings() });
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.patterns() });
    },
  });
}

/**
 * Update risk scoring weights and thresholds
 */
export function useUpdateRiskScoringSettings() {
  const qc: QueryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: RiskScoringSettings) =>
      api.put<RiskScoringSettings>("/v1/governance/risk-scoring", settings).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData<GovernanceSettings | undefined>(
        GOVERNANCE_KEYS.settings(),
        (current: GovernanceSettings | undefined) => current ? { ...current, riskScoring: data } : current
      );
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.settings() });
      qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.riskScoring() });
    },
  });
}
