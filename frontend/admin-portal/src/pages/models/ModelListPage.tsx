import { Link } from "react-router-dom";
import { MixerHorizontalIcon, PlusIcon } from "@radix-ui/react-icons";

import { useModels } from "../../services/modelService";
import { ModelRow } from "../../components/models/ModelRow";
import { CostAnalyticsPanel } from "../../components/models/CostAnalyticsPanel";
import { PageHeader } from "../../components/ui/PageHeader";
import { GlassCard } from "../../components/ui/GlassCard";
import { StatCard } from "../../components/ui/StatCard";

export function ModelListPage() {
  const { data: models, isLoading, isError } = useModels();

  if (isLoading) {
    return (
      <main className="page-layout">
        <div role="status" aria-label="Loading models" className="text-secondary py-8">
          Loading…
        </div>
      </main>
    );
  }
  if (isError) {
    return (
      <main className="page-layout">
        <div role="alert" className="text-red-600 py-4">
          Failed to load models.
        </div>
      </main>
    );
  }

  const total = models?.length ?? 0;
  const active = models?.filter((m) => m.is_active).length ?? 0;
  const avgCost =
    total > 0 ? (models!.reduce((sum, m) => sum + m.cost_per_1k_tokens, 0) / total) : 0;

  return (
    <main aria-labelledby="models-heading" className="page-layout">
      <PageHeader
        headingId="models-heading"
        title="Models"
        subtitle="Registered LLMs available to the Dynamic Model Router."
        actions={
          <>
            <Link to="/models/weights" className="btn-secondary">
              <MixerHorizontalIcon aria-hidden="true" />
              Routing Weights
            </Link>
            <Link to="/models/add" className="btn-primary">
              <PlusIcon aria-hidden="true" />
              Register Model
            </Link>
          </>
        }
      />

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Registered Models" value={total} accent="primary" />
        <StatCard label="Active" value={active} accent="success" delay={40} />
        <StatCard
          label="Avg. Cost / 1K tokens"
          value={avgCost}
          decimals={4}
          prefix="$"
          accent="info"
          delay={80}
        />
      </div>

      <GlassCard className="overflow-x-auto p-0" delay={120}>
        <table className="w-full min-w-[800px] text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-secondary">
              <th scope="col" className="px-4 py-3">Model ID</th>
              <th scope="col" className="px-4 py-3">Provider</th>
              <th scope="col" className="px-4 py-3">Context Window</th>
              <th scope="col" className="px-4 py-3">Cost / 1k</th>
              <th scope="col" className="px-4 py-3">Latency</th>
              <th scope="col" className="px-4 py-3">Capabilities</th>
              <th scope="col" className="px-4 py-3">Active</th>
            </tr>
          </thead>
          <tbody>
            {(models ?? []).map((model) => (
              <ModelRow key={model.id} model={model} />
            ))}
          </tbody>
        </table>
      </GlassCard>

      <div className="mt-6">
        <GlassCard className="p-5" delay={160}>
          <CostAnalyticsPanel />
        </GlassCard>
      </div>
    </main>
  );
}
