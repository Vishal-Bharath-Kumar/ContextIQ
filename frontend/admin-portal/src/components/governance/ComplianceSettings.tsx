import { useState, useEffect } from "react";
import { CheckIcon, Cross2Icon } from "@radix-ui/react-icons";
import { useQueryClient } from "@tanstack/react-query";

import {
  GOVERNANCE_KEYS,
  type GovernanceSettings,
  useGovernanceSettings,
  useUpdateComplianceSettings,
  type ComplianceStandard,
} from "../../services/governanceService";

export function ComplianceSettings() {
  const qc = useQueryClient();
  const { data: governanceSettings, isLoading } = useGovernanceSettings();
  const updateMutation = useUpdateComplianceSettings();
  
  const [standards, setStandards] = useState<ComplianceStandard[]>([]);
  const [saved, setSaved] = useState(false);

  // Load data from API
  useEffect(() => {
    if (governanceSettings?.compliance?.standards) {
      setStandards(governanceSettings.compliance.standards);
    }
  }, [governanceSettings]);

  const setCompliancePreview = (nextStandards: ComplianceStandard[]) => {
    qc.setQueryData<GovernanceSettings | undefined>(
      GOVERNANCE_KEYS.settings(),
      (current) =>
        current
          ? {
              ...current,
              compliance: {
                ...current.compliance,
                standards: nextStandards,
              },
            }
          : current
    );
  };

  const toggleStandard = (id: string) => {
    setStandards((prev) => {
      const nextStandards = prev.map((std) =>
        std.id === id ? { ...std, enabled: !std.enabled } : std
      );
      // Optimistic preview: keep Governance metrics in sync with unsaved toggles.
      setCompliancePreview(nextStandards);
      return nextStandards;
    });
    setSaved(false);
  };

  const handleSave = async () => {
    try {
      await updateMutation.mutateAsync({ standards });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      // Roll back optimistic preview to server truth.
      await qc.invalidateQueries({ queryKey: GOVERNANCE_KEYS.settings() });
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-sm text-slate-600">Loading compliance settings...</p>
      </div>
    );
  }

  const enabledCount = standards.filter((s) => s.enabled).length;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 mb-2">
          Compliance Standards
        </h2>
        <p className="text-sm text-slate-600">
          Enable compliance validation for regulatory standards. Enabled standards will be checked
          during governance scans.
        </p>
        <div className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 bg-indigo-50 border border-indigo-200 rounded-lg">
          <span className="text-xs font-medium text-indigo-900">
            {enabledCount} of {standards.length} standards enabled
          </span>
        </div>
      </div>

      <div className="space-y-3">
        {standards.map((standard) => (
          <div
            key={standard.id}
            className={`
              p-4 border rounded-lg transition-all duration-200
              ${
                standard.enabled
                  ? "bg-green-50/50 border-green-200"
                  : "bg-slate-50/50 border-slate-200"
              }
            `}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <h3 className="text-sm font-semibold text-slate-900">
                    {standard.name}
                  </h3>
                  {standard.enabled && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-800 text-xs font-medium rounded">
                      <CheckIcon className="w-3 h-3" />
                      Enabled
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-600 mb-2">{standard.description}</p>
                <p className="text-xs text-slate-500">
                  {standard.requirementCount} validation rules
                </p>
              </div>

              <button
                onClick={() => toggleStandard(standard.id)}
                className={`
                  relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full
                  border-2 border-transparent transition-colors duration-200 ease-in-out
                  focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
                  ${standard.enabled ? "bg-indigo-600" : "bg-slate-300"}
                `}
                role="switch"
                aria-checked={standard.enabled}
                aria-label={`Toggle ${standard.name}`}
              >
                <span
                  className={`
                    pointer-events-none inline-block h-5 w-5 transform rounded-full
                    bg-white shadow ring-0 transition duration-200 ease-in-out
                    ${standard.enabled ? "translate-x-5" : "translate-x-0"}
                  `}
                />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200">
        <div>
          {saved && (
            <span className="inline-flex items-center gap-2 text-sm text-green-600">
              <CheckIcon className="w-4 h-4" />
              Settings saved successfully
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

      {/* Warning about enabled standards */}
      {enabledCount === 0 && (
        <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-sm text-yellow-800">
            ⚠️ <strong>Warning:</strong> No compliance standards are enabled. Your governance
            scans will not validate compliance requirements.
          </p>
        </div>
      )}
    </div>
  );
}
