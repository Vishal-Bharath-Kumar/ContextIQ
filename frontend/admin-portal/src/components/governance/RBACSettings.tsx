import { useState, useEffect } from "react";
import { CheckIcon, Cross2Icon } from "@radix-ui/react-icons";

import {
  useGovernanceSettings,
  useUpdateRBACSettings,
  type RolePermissions,
} from "../../services/governanceService";

const PERMISSIONS = ["READ", "WRITE", "DELETE", "DEBUG", "ADMIN", "EXECUTE"];

export function RBACSettings() {
  const { data: governanceSettings, isLoading } = useGovernanceSettings();
  const updateMutation = useUpdateRBACSettings();
  
  const [roles, setRoles] = useState<RolePermissions[]>([]);
  const [saved, setSaved] = useState(false);

  // Load data from API
  useEffect(() => {
    if (governanceSettings?.rbac?.roles) {
      setRoles(governanceSettings.rbac.roles);
    }
  }, [governanceSettings]);

  const handleSave = async () => {
    await updateMutation.mutateAsync({ roles });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-sm text-slate-600">Loading RBAC settings...</p>
      </div>
    );
  }

  const getColorClasses = (color: string, active: boolean) => {
    const colors: Record<string, string> = {
      purple: active ? "bg-purple-100 text-purple-800 border-purple-200" : "bg-slate-50 text-slate-400 border-slate-200",
      blue: active ? "bg-blue-100 text-blue-800 border-blue-200" : "bg-slate-50 text-slate-400 border-slate-200",
      green: active ? "bg-green-100 text-green-800 border-green-200" : "bg-slate-50 text-slate-400 border-slate-200",
      gray: active ? "bg-gray-100 text-gray-800 border-gray-200" : "bg-slate-50 text-slate-400 border-slate-200",
      slate: active ? "bg-slate-100 text-slate-800 border-slate-200" : "bg-slate-50 text-slate-400 border-slate-200",
    };
    return colors[color] || colors.slate;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 mb-2">
          Role-Based Access Control (RBAC)
        </h2>
        <p className="text-sm text-slate-600">
          Configure permissions and data access levels for each user role. These settings
          determine what actions users can perform and what data classification levels they can
          access.
        </p>
      </div>

      {/* Role Permission Matrix */}
      <div className="overflow-x-auto">
        <table className="w-full border border-slate-200 rounded-lg">
          <thead>
            <tr className="bg-slate-50">
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 border-b border-slate-200">
                Role
              </th>
              {PERMISSIONS.map((perm) => (
                <th
                  key={perm}
                  className="px-4 py-3 text-center text-xs font-semibold text-slate-700 border-b border-slate-200"
                >
                  {perm}
                </th>
              ))}
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-700 border-b border-slate-200">
                Max Classification
              </th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role, idx) => (
              <tr
                key={role.role}
                className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}
              >
                <td className="px-4 py-3 border-b border-slate-200">
                  <span className={`inline-flex px-3 py-1 text-xs font-semibold rounded-full ${getColorClasses(role.color, true)}`}>
                    {role.displayName}
                  </span>
                </td>
                {PERMISSIONS.map((perm) => {
                  const hasPermission = role.permissions.includes(perm);
                  return (
                    <td
                      key={perm}
                      className="px-4 py-3 text-center border-b border-slate-200"
                    >
                      {hasPermission ? (
                        <CheckIcon className="w-5 h-5 text-green-600 mx-auto" />
                      ) : (
                        <Cross2Icon className="w-5 h-5 text-slate-300 mx-auto" />
                      )}
                    </td>
                  );
                })}
                <td className="px-4 py-3 border-b border-slate-200">
                  <span className={`inline-flex px-2 py-1 text-xs font-medium rounded ${
                    role.maxClassification === "SECRET" ? "bg-red-100 text-red-800" :
                    role.maxClassification === "RESTRICTED" ? "bg-orange-100 text-orange-800" :
                    role.maxClassification === "CONFIDENTIAL" ? "bg-yellow-100 text-yellow-800" :
                    role.maxClassification === "INTERNAL" ? "bg-blue-100 text-blue-800" :
                    role.maxClassification === "PUBLIC" ? "bg-green-100 text-green-800" :
                    "bg-slate-100 text-slate-800"
                  }`}>
                    {role.maxClassification}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Data Classification Info */}
      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h3 className="text-sm font-semibold text-blue-900 mb-2">
          Data Classification Levels
        </h3>
        <div className="space-y-1 text-sm text-blue-800">
          <div className="flex items-center gap-2">
            <span className="inline-flex px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800">
              PUBLIC
            </span>
            <span>Accessible by all roles</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex px-2 py-0.5 text-xs font-medium rounded bg-blue-100 text-blue-800">
              INTERNAL
            </span>
            <span>Admin, Developer, Analyst</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-800">
              CONFIDENTIAL
            </span>
            <span>Admin, Developer only</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex px-2 py-0.5 text-xs font-medium rounded bg-orange-100 text-orange-800">
              RESTRICTED
            </span>
            <span>Admin only</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex px-2 py-0.5 text-xs font-medium rounded bg-red-100 text-red-800">
              SECRET
            </span>
            <span>Admin only</span>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-200">
        <div>
          {saved && (
            <span className="inline-flex items-center gap-2 text-sm text-green-600">
              <CheckIcon className="w-4 h-4" />
              RBAC settings saved successfully
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
