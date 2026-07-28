import { useState } from "react";
import { GearIcon, CheckCircledIcon, LockClosedIcon, FileTextIcon } from "@radix-ui/react-icons";

import { PageHeader } from "../../components/ui/PageHeader";
import { GlassCard } from "../../components/ui/GlassCard";
import { ComplianceSettings } from "../../components/governance/ComplianceSettings";
import { RBACSettings } from "../../components/governance/RBACSettings";
import { PatternDetectionSettings } from "../../components/governance/PatternDetectionSettings";
import { RiskScoringSettings } from "../../components/governance/RiskScoringSettings";
import { GovernanceMetrics } from "../../components/governance/GovernanceMetrics";

type TabType = "compliance" | "rbac" | "patterns" | "risk";

export function GovernanceSettingsPage() {
  const [activeTab, setActiveTab] = useState<TabType>("compliance");

  const tabs: { id: TabType; label: string; icon: JSX.Element }[] = [
    { id: "compliance", label: "Compliance Standards", icon: <CheckCircledIcon /> },
    { id: "rbac", label: "RBAC & Permissions", icon: <LockClosedIcon /> },
    { id: "patterns", label: "Pattern Detection", icon: <FileTextIcon /> },
    { id: "risk", label: "Risk Scoring", icon: <GearIcon /> },
  ];

  return (
    <main aria-labelledby="governance-heading" className="page-layout">
      <PageHeader
        headingId="governance-heading"
        title="Governance Settings"
        subtitle="Configure comprehensive security, compliance, and risk management policies."
      />

      {/* Metrics Dashboard */}
      <GovernanceMetrics />

      {/* Settings Tabs */}
      <GlassCard className="p-0 overflow-hidden">
        <div className="border-b border-slate-200/50 bg-slate-50/50">
          <nav className="flex space-x-1 p-2" aria-label="Governance settings tabs">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`
                  flex items-center gap-2 px-4 py-3 text-sm font-medium rounded-lg
                  transition-all duration-200
                  ${
                    activeTab === tab.id
                      ? "bg-white text-indigo-600 shadow-sm"
                      : "text-slate-600 hover:bg-white/50 hover:text-slate-900"
                  }
                `}
                aria-current={activeTab === tab.id ? "page" : undefined}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="p-6">
          {activeTab === "compliance" && <ComplianceSettings />}
          {activeTab === "rbac" && <RBACSettings />}
          {activeTab === "patterns" && <PatternDetectionSettings />}
          {activeTab === "risk" && <RiskScoringSettings />}
        </div>
      </GlassCard>

      {/* Help Text */}
      <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h3 className="text-sm font-semibold text-blue-900 mb-2">
          ℹ️ About Governance Settings
        </h3>
        <p className="text-sm text-blue-800">
          These settings control how ContextIQ scans, validates, and protects sensitive content
          before it reaches AI models. All changes are logged for audit compliance.
        </p>
      </div>
    </main>
  );
}
