import { useState, useEffect } from "react";
import { CheckIcon, MagnifyingGlassIcon, Cross2Icon } from "@radix-ui/react-icons";

import {
  useGovernanceSettings,
  useUpdatePatternSettings,
  type PatternCategory,
} from "../../services/governanceService";

export function PatternDetectionSettings() {
  const { data: governanceSettings, isLoading } = useGovernanceSettings();
  const updateMutation = useUpdatePatternSettings();
  
  const [categories, setCategories] = useState<PatternCategory[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [saved, setSaved] = useState(false);

  // Load data from API
  useEffect(() => {
    if (governanceSettings?.patterns?.categories) {
      setCategories(governanceSettings.patterns.categories);
    }
  }, [governanceSettings]);

  const togglePattern = (categoryId: string, patternId: string) => {
    setCategories((prev) =>
      prev.map((cat) =>
        cat.id === categoryId
          ? {
              ...cat,
              patterns: cat.patterns.map((p) =>
                p.id === patternId ? { ...p, enabled: !p.enabled } : p
              ),
            }
          : cat
      )
    );
    setSaved(false);
  };

  const toggleCategory = (categoryId: string, enabled: boolean) => {
    setCategories((prev) =>
      prev.map((cat) =>
        cat.id === categoryId
          ? {
              ...cat,
              patterns: cat.patterns.map((p) => ({ ...p, enabled })),
            }
          : cat
      )
    );
    setSaved(false);
  };

  const handleSave = async () => {
    await updateMutation.mutateAsync({ categories });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-sm text-slate-600">Loading pattern settings...</p>
      </div>
    );
  }

  const totalPatterns = categories.reduce((sum, cat) => sum + cat.patterns.length, 0);
  const enabledPatterns = categories.reduce(
    (sum, cat) => sum + cat.patterns.filter((p) => p.enabled).length,
    0
  );

  const filteredCategories = searchTerm
    ? categories
        .map((cat) => ({
          ...cat,
          patterns: cat.patterns.filter(
            (p) =>
              p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
              p.id.toLowerCase().includes(searchTerm.toLowerCase())
          ),
        }))
        .filter((cat) => cat.patterns.length > 0)
    : categories;

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "CRITICAL":
        return "bg-red-100 text-red-800 border-red-200";
      case "HIGH":
        return "bg-orange-100 text-orange-800 border-orange-200";
      case "MEDIUM":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      case "LOW":
        return "bg-blue-100 text-blue-800 border-blue-200";
      case "INFO":
        return "bg-slate-100 text-slate-800 border-slate-200";
      default:
        return "bg-slate-100 text-slate-800 border-slate-200";
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 mb-2">
          Pattern Detection Configuration
        </h2>
        <p className="text-sm text-slate-600 mb-4">
          Configure which secret and PII patterns to detect during governance scans. Disabled
          patterns will not trigger findings or redactions.
        </p>

        <div className="flex items-center justify-between gap-4">
          <div className="flex-1 relative">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search patterns..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-2 bg-indigo-50 border border-indigo-200 rounded-lg">
            <span className="text-xs font-medium text-indigo-900">
              {enabledPatterns} / {totalPatterns} patterns enabled
            </span>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        {filteredCategories.map((category) => {
          const categoryEnabled = category.patterns.every((p) => p.enabled);
          const categoryDisabled = category.patterns.every((p) => !p.enabled);
          const categoryEnabledCount = category.patterns.filter((p) => p.enabled).length;

          return (
            <div
              key={category.id}
              className="border border-slate-200 rounded-lg overflow-hidden"
            >
              <div className="bg-slate-50 px-4 py-3 flex items-center justify-between">
                <div className="flex-1">
                  <h3 className="text-sm font-semibold text-slate-900">
                    {category.name}
                  </h3>
                  <p className="text-xs text-slate-600 mt-0.5">{category.description}</p>
                  <div className="mt-2 text-xs text-slate-500">
                    {categoryEnabledCount} of {category.patterns.length} patterns enabled
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggleCategory(category.id, true)}
                    disabled={categoryEnabled}
                    className="px-3 py-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded hover:bg-green-100 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Enable All
                  </button>
                  <button
                    onClick={() => toggleCategory(category.id, false)}
                    disabled={categoryDisabled}
                    className="px-3 py-1 text-xs font-medium text-slate-700 bg-slate-100 border border-slate-200 rounded hover:bg-slate-200 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Disable All
                  </button>
                </div>
              </div>

              <div className="divide-y divide-slate-200">
                {category.patterns.map((pattern) => (
                  <div
                    key={pattern.id}
                    className={`px-4 py-3 flex items-center justify-between ${
                      !pattern.enabled ? "bg-slate-50/50" : "bg-white"
                    }`}
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-medium text-slate-900">
                          {pattern.name}
                        </span>
                        <span
                          className={`inline-flex px-2 py-0.5 text-xs font-medium rounded border ${getSeverityColor(
                            pattern.severity
                          )}`}
                        >
                          {pattern.severity}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                        <code className="px-1.5 py-0.5 bg-slate-100 rounded font-mono">
                          {pattern.id}
                        </code>
                        {pattern.matchCount !== undefined && (
                          <span>• {pattern.matchCount.toLocaleString()} matches (last 30d)</span>
                        )}
                      </div>
                    </div>

                    <button
                      onClick={() => togglePattern(category.id, pattern.id)}
                      className={`
                        relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full
                        border-2 border-transparent transition-colors duration-200 ease-in-out
                        focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
                        ${pattern.enabled ? "bg-indigo-600" : "bg-slate-300"}
                      `}
                      role="switch"
                      aria-checked={pattern.enabled}
                      aria-label={`Toggle ${pattern.name}`}
                    >
                      <span
                        className={`
                          pointer-events-none inline-block h-5 w-5 transform rounded-full
                          bg-white shadow ring-0 transition duration-200 ease-in-out
                          ${pattern.enabled ? "translate-x-5" : "translate-x-0"}
                        `}
                      />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200">
        <div>
          {saved && (
            <span className="inline-flex items-center gap-2 text-sm text-green-600">
              <CheckIcon className="w-4 h-4" />
              Pattern settings saved successfully
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
