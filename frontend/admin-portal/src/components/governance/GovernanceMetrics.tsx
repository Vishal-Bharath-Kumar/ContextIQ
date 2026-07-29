import { CheckCircledIcon, ExclamationTriangleIcon, LockClosedIcon, FileTextIcon } from "@radix-ui/react-icons";
import { usePolicies } from "../../services/policyService";
import { useGovernanceSettings } from "../../services/governanceService";

interface MetricCard {
  title: string;
  value: string | number;
  change?: string;
  changeType?: "positive" | "negative" | "neutral";
  icon: JSX.Element;
  color: string;
}

export function GovernanceMetrics() {
  const { data: policies } = usePolicies();
  const { data: governanceSettings } = useGovernanceSettings();

  const totalPolicies = policies?.length ?? 0;
  const activePolicies = policies?.filter((policy) => policy.active_version !== null).length ?? 0;

  const standards = governanceSettings?.compliance.standards ?? [];
  const totalStandards = standards.length;
  const disabledStandards = standards.filter((standard) => !standard.enabled).length;
  const enabledStandards = totalStandards - disabledStandards;

  const categories = governanceSettings?.patterns.categories ?? [];
  const piiCategory = categories.find((category) => category.id === "pii");
  const secretCategories = categories.filter((category) => category.id !== "pii");

  const secretsMasked = secretCategories.reduce(
    (sum, category) =>
      sum +
      category.patterns.reduce(
        (categorySum, pattern) => categorySum + (pattern.enabled ? (pattern.matchCount ?? 0) : 0),
        0
      ),
    0
  );

  const piiProtected = (piiCategory?.patterns ?? []).reduce(
    (sum, pattern) => sum + (pattern.enabled ? (pattern.matchCount ?? 0) : 0),
    0
  );

  const policyCoveragePct =
    totalPolicies === 0 ? 0 : Math.round((activePolicies / totalPolicies) * 100);

  const metrics: MetricCard[] = [
    {
      title: "Policies Applied",
      value: `${activePolicies}/${totalPolicies}`,
      change: `${policyCoveragePct}% active`,
      changeType: policyCoveragePct === 100 ? "positive" : "neutral",
      icon: <CheckCircledIcon className="w-6 h-6" />,
      color: "green",
    },
    {
      title: "Secrets Masked",
      value: secretsMasked.toLocaleString(),
      change: `${secretCategories.length} categories`,
      changeType: "neutral",
      icon: <LockClosedIcon className="w-6 h-6" />,
      color: "blue",
    },
    {
      title: "PII Protected",
      value: piiProtected.toLocaleString(),
      change: `${(piiCategory?.patterns ?? []).filter((pattern) => pattern.enabled).length} patterns enabled`,
      changeType: "neutral",
      icon: <FileTextIcon className="w-6 h-6" />,
      color: "purple",
    },
    {
      title: "Compliance Violations",
      value: disabledStandards,
      change: `${enabledStandards}/${totalStandards} standards enabled`,
      changeType: disabledStandards === 0 ? "positive" : "negative",
      icon: <ExclamationTriangleIcon className="w-6 h-6" />,
      color: "orange",
    },
  ];

  const getColorClasses = (color: string) => {
    const colors: Record<string, { bg: string; text: string; border: string }> = {
      green: {
        bg: "bg-green-50",
        text: "text-green-600",
        border: "border-green-200",
      },
      blue: {
        bg: "bg-blue-50",
        text: "text-blue-600",
        border: "border-blue-200",
      },
      purple: {
        bg: "bg-purple-50",
        text: "text-purple-600",
        border: "border-purple-200",
      },
      orange: {
        bg: "bg-orange-50",
        text: "text-orange-600",
        border: "border-orange-200",
      },
    };
    return colors[color] || colors.green;
  };

  const getChangeColor = (type: "positive" | "negative" | "neutral" | undefined) => {
    switch (type) {
      case "positive":
        return "text-green-600";
      case "negative":
        return "text-red-600";
      case "neutral":
        return "text-slate-600";
      default:
        return "text-slate-600";
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {metrics.map((metric, index) => {
        const colorClasses = getColorClasses(metric.color);
        return (
          <div
            key={metric.title}
            className={`
              p-5 border rounded-lg bg-white shadow-sm
              transition-all duration-300 hover:shadow-md
              ${colorClasses.border}
            `}
            style={{
              animation: `fadeInUp 0.5s ease-out ${index * 100}ms both`,
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <div
                className={`
                  p-2 rounded-lg
                  ${colorClasses.bg}
                `}
              >
                <div className={colorClasses.text}>{metric.icon}</div>
              </div>
              {metric.change && (
                <span className={`text-xs font-medium ${getChangeColor(metric.changeType)}`}>
                  {metric.change}
                </span>
              )}
            </div>
            <div className="text-2xl font-bold text-slate-900 mb-1">{metric.value}</div>
            <div className="text-sm text-slate-600">{metric.title}</div>
          </div>
        );
      })}
    </div>
  );
}
