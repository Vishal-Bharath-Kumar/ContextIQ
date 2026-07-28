import { useState, useEffect } from "react";
import { CheckIcon, Cross2Icon } from "@radix-ui/react-icons";

import {
  useGovernanceSettings,
  useUpdateRiskScoringSettings,
  type SeverityWeight,
} from "../../services/governanceService";

interface RiskThreshold {
  level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  minScore: number;
  maxScore: number;
  color: string;
  action: string;
}

const RISK_THRESHOLDS: RiskThreshold[] = [
  {
    level: "LOW",
    minScore: 0.0,
    maxScore: 2.0,
    color: "green",
    action: "Allow with logging",
  },
  {
    level: "MEDIUM",
    minScore: 2.1,
    maxScore: 5.0,
    color: "yellow",
    action: "Allow with masking",
  },
  {
    level: "HIGH",
    minScore: 5.1,
    maxScore: 8.0,
    color: "orange",
    action: "Allow with masking + alert",
  },
  {
    level: "CRITICAL",
    minScore: 8.1,
    maxScore: 10.0,
    color: "red",
    action: "Block + alert",
  },
];

export function RiskScoringSettings() {
  const { data: governanceSettings, isLoading } = useGovernanceSettings();
  const updateMutation = useUpdateRiskScoringSettings();
  
  const [weights, setWeights] = useState<SeverityWeight[]>([]);
  const [violationPenalty, setViolationPenalty] = useState(0.5);
  const [saved, setSaved] = useState(false);

  // Load data from API
  useEffect(() => {
    if (governanceSettings?.riskScoring) {
      setWeights(governanceSettings.riskScoring.severityWeights);
      setViolationPenalty(governanceSettings.riskScoring.violationPenalty);
    }
  }, [governanceSettings]);

  const handleWeightChange = (severity: string, newWeight: number) => {
    setWeights((prev) =>
      prev.map((w) => (w.severity === severity ? { ...w, weight: newWeight } : w))
    );
    setSaved(false);
  };

  const handleSave = async () => {
    await updateMutation.mutateAsync({
      severityWeights: weights,
      violationPenalty,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-sm text-slate-600">Loading risk scoring settings...</p>
      </div>
    );
  }

  const getRiskColor = (color: string) => {
    const colors: Record<string, string> = {
      green: "bg-green-50 border-green-200",
      yellow: "bg-yellow-50 border-yellow-200",
      orange: "bg-orange-50 border-orange-200",
      red: "bg-red-50 border-red-200",
    };
    return colors[color] || colors.green;
  };

  const getRiskTextColor = (color: string) => {
    const colors: Record<string, string> = {
      green: "text-green-900",
      yellow: "text-yellow-900",
      orange: "text-orange-900",
      red: "text-red-900",
    };
    return colors[color] || colors.green;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 mb-2">Risk Scoring Configuration</h2>
        <p className="text-sm text-slate-600">
          Configure how governance findings are weighted to calculate an overall risk score (0-10).
          Risk scores determine whether content is allowed, masked, or blocked.
        </p>
      </div>

      {/* Risk Level Thresholds */}
      <div>
        <h3 className="text-sm font-semibold text-slate-900 mb-3">Risk Level Thresholds</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {RISK_THRESHOLDS.map((threshold) => (
            <div
              key={threshold.level}
              className={`p-4 border rounded-lg ${getRiskColor(threshold.color)}`}
            >
              <div className={`text-sm font-semibold mb-1 ${getRiskTextColor(threshold.color)}`}>
                {threshold.level}
              </div>
              <div className="text-2xl font-bold text-slate-900 mb-2">
                {threshold.minScore} - {threshold.maxScore}
              </div>
              <div className="text-xs text-slate-600">{threshold.action}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Severity Weights */}
      <div>
        <h3 className="text-sm font-semibold text-slate-900 mb-3">Severity Weights</h3>
        <p className="text-xs text-slate-600 mb-4">
          Each finding's severity contributes to the total risk score. Adjust these weights to
          prioritize different types of findings.
        </p>

        <div className="space-y-3">
          {weights.map((weight) => (
            <div
              key={weight.severity}
              className="p-4 border border-slate-200 rounded-lg bg-white"
            >
              <div className="flex items-center justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900">
                      {weight.severity}
                    </span>
                    <span
                      className={`inline-flex px-2 py-0.5 text-xs font-medium rounded ${
                        weight.severity === "CRITICAL"
                          ? "bg-red-100 text-red-800"
                          : weight.severity === "HIGH"
                          ? "bg-orange-100 text-orange-800"
                          : weight.severity === "MEDIUM"
                          ? "bg-yellow-100 text-yellow-800"
                          : weight.severity === "LOW"
                          ? "bg-blue-100 text-blue-800"
                          : "bg-slate-100 text-slate-800"
                      }`}
                    >
                      Weight: {weight.weight}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 mt-1">{weight.description}</p>
                </div>
              </div>

              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="0"
                  max="10"
                  step="0.1"
                  value={weight.weight}
                  onChange={(e) =>
                    handleWeightChange(weight.severity, parseFloat(e.target.value))
                  }
                  className="flex-1 h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                />
                <input
                  type="number"
                  min="0"
                  max="10"
                  step="0.1"
                  value={weight.weight}
                  onChange={(e) =>
                    handleWeightChange(weight.severity, parseFloat(e.target.value) || 0)
                  }
                  className="w-20 px-2 py-1 border border-slate-300 rounded text-sm text-center"
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Violation Penalty */}
      <div>
        <h3 className="text-sm font-semibold text-slate-900 mb-3">Compliance Violation Penalty</h3>
        <p className="text-xs text-slate-600 mb-4">
          Additional penalty added to risk score per compliance violation (e.g., GDPR, SOC2
          violations). Maximum penalty capped at 3.0.
        </p>

        <div className="p-4 border border-slate-200 rounded-lg bg-white">
          <div className="flex items-center gap-4">
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={violationPenalty}
              onChange={(e) => {
                setViolationPenalty(parseFloat(e.target.value));
                setSaved(false);
              }}
              className="flex-1 h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
            />
            <div className="flex items-center gap-2">
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={violationPenalty}
                onChange={(e) => {
                  setViolationPenalty(parseFloat(e.target.value) || 0);
                  setSaved(false);
                }}
                className="w-20 px-2 py-1 border border-slate-300 rounded text-sm text-center"
              />
              <span className="text-sm text-slate-600">per violation</span>
            </div>
          </div>
        </div>
      </div>

      {/* Example Calculation */}
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h3 className="text-sm font-semibold text-blue-900 mb-2">
          Example Risk Score Calculation
        </h3>
        <div className="text-sm text-blue-800 space-y-1">
          <div>• 2 CRITICAL findings: 2 × {weights.find(w => w.severity === "CRITICAL")?.weight} = {(2 * (weights.find(w => w.severity === "CRITICAL")?.weight || 5)).toFixed(1)}</div>
          <div>• 3 HIGH findings: 3 × {weights.find(w => w.severity === "HIGH")?.weight} = {(3 * (weights.find(w => w.severity === "HIGH")?.weight || 3)).toFixed(1)}</div>
          <div>• 1 compliance violation: 1 × {violationPenalty} = {violationPenalty.toFixed(1)}</div>
          <div className="pt-2 border-t border-blue-300 font-semibold">
            Total Risk Score: {Math.min((2 * (weights.find(w => w.severity === "CRITICAL")?.weight || 5)) + (3 * (weights.find(w => w.severity === "HIGH")?.weight || 3)) + violationPenalty, 10).toFixed(1)} / 10.0
            {" "}({
              Math.min((2 * (weights.find(w => w.severity === "CRITICAL")?.weight || 5)) + (3 * (weights.find(w => w.severity === "HIGH")?.weight || 3)) + violationPenalty, 10) >= 8.1 ? "CRITICAL" :
              Math.min((2 * (weights.find(w => w.severity === "CRITICAL")?.weight || 5)) + (3 * (weights.find(w => w.severity === "HIGH")?.weight || 3)) + violationPenalty, 10) >= 5.1 ? "HIGH" :
              Math.min((2 * (weights.find(w => w.severity === "CRITICAL")?.weight || 5)) + (3 * (weights.find(w => w.severity === "HIGH")?.weight || 3)) + violationPenalty, 10) >= 2.1 ? "MEDIUM" : "LOW"
            })
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200">
        <div>
          {saved && (
            <span className="inline-flex items-center gap-2 text-sm text-green-600">
              <CheckIcon className="w-4 h-4" />
              Risk scoring settings saved successfully
            </span>
          )}
          {updateMutation.isError && (
            <span className="inline-flex items-center gap-2 text-sm text-red-600">
              <Cross2Icon className="w-4 h-4" />
              Failed to save settings
            </span>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={updateMutation.isPending || saved}
          className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {updateMutation.isPending ? "Saving..." : "Save Changes"}
        </button>
      </div>
    </div>
  );
}
