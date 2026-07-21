import { useMemo } from "react";
import { Link } from "react-router-dom";
import { PlusIcon } from "@radix-ui/react-icons";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { useTools } from "../../services/toolRegistryService";
import { ToolRow } from "../../components/tools/ToolRow";
import { PageHeader } from "../../components/ui/PageHeader";
import { GlassCard } from "../../components/ui/GlassCard";
import { EmptyState } from "../../components/ui/EmptyState";
import { StatCard } from "../../components/ui/StatCard";

const STATUS_COLORS: Record<string, string> = {
  active: "#10b981",
  inactive: "#94a3b8",
};

export function ToolRegistryListPage() {
  const { data: tools, isLoading, isError } = useTools();

  const total = tools?.length ?? 0;
  const active = tools?.filter((t) => t.status === "active").length ?? 0;
  const inactive = total - active;

  const statusData = useMemo(() => {
    if (!tools || tools.length === 0) return [];
    return [
      { status: "active", count: active },
      { status: "inactive", count: inactive },
    ].filter((entry) => entry.count > 0);
  }, [tools, active, inactive]);

  return (
    <main aria-labelledby="tools-heading" className="page-layout">
      <PageHeader
        headingId="tools-heading"
        title="Tool Registry"
        subtitle="MCP tools available to agents — register, version, and govern tool availability."
        actions={
          <Link to="/tools/add" className="btn-primary">
            <PlusIcon aria-hidden="true" />
            Register Tool
          </Link>
        }
      />

      {isLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading tools…
        </p>
      )}

      {isError && (
        <p role="alert" className="text-red-600 py-4">
          Failed to load the tool registry. Please try again.
        </p>
      )}

      {!isLoading && !isError && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Registered Tools" value={total} accent="primary" />
            <StatCard label="Active" value={active} accent="success" delay={40} />
            <StatCard label="Inactive" value={inactive} accent="warning" delay={80} />
          </div>

          {total === 0 ? (
            <EmptyState
              title="No tools registered yet"
              description="Register MCP tools so agents can discover and safely invoke enterprise capabilities."
              action={
                <Link to="/tools/add" className="btn-primary">
                  Register your first tool
                </Link>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <GlassCard className="overflow-x-auto p-0 lg:col-span-2" delay={120}>
                <table className="w-full min-w-[720px] text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-secondary">
                      <th scope="col" className="px-4 py-3">Tool</th>
                      <th scope="col" className="px-4 py-3">Version</th>
                      <th scope="col" className="px-4 py-3">Status</th>
                      <th scope="col" className="px-4 py-3">Updated</th>
                      <th scope="col" className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(tools ?? []).map((tool) => (
                      <ToolRow key={tool.id} tool={tool} />
                    ))}
                  </tbody>
                </table>
              </GlassCard>

              <GlassCard className="p-5" delay={160}>
                <h2 className="mb-4 text-sm font-semibold text-slate-800">Tool Status Mix</h2>
                {statusData.length === 0 ? (
                  <p className="py-10 text-center text-sm text-secondary">No data yet.</p>
                ) : (
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie
                        data={statusData}
                        dataKey="count"
                        nameKey="status"
                        innerRadius={50}
                        outerRadius={80}
                        paddingAngle={4}
                      >
                        {statusData.map((entry) => (
                          <Cell key={entry.status} fill={STATUS_COLORS[entry.status] ?? "#6366f1"} />
                        ))}
                      </Pie>
                      <Tooltip />
                      <Legend formatter={(v: string) => <span className="text-xs capitalize">{v}</span>} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </GlassCard>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
