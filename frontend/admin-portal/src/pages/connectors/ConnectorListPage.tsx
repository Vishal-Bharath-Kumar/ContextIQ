import { Link } from "react-router-dom";
import { PlusIcon } from "@radix-ui/react-icons";

import { useConnectors } from "../../services/connectorService";
import { ConnectorRow } from "../../components/connectors/ConnectorRow";
import { PageHeader } from "../../components/ui/PageHeader";
import { GlassCard } from "../../components/ui/GlassCard";
import { EmptyState } from "../../components/ui/EmptyState";
import { StatCard } from "../../components/ui/StatCard";

export function ConnectorListPage() {
  const { data: connectors, isLoading, isError } = useConnectors();

  const total = connectors?.length ?? 0;
  const active = connectors?.filter((c) => c.status === "active").length ?? 0;
  const documents = connectors?.reduce((sum, c) => sum + c.document_count, 0) ?? 0;

  return (
    <main aria-labelledby="connectors-heading" className="page-layout">
      <PageHeader
        headingId="connectors-heading"
        title="Connectors"
        subtitle="Manage enterprise knowledge sources that feed the ContextIQ knowledge graph."
        actions={
          <Link to="/connectors/add" className="btn-primary">
            <PlusIcon aria-hidden="true" />
            Add Connector
          </Link>
        }
      />

      {isLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading connectors…
        </p>
      )}

      {isError && (
        <p role="alert" className="text-red-600 py-4">
          Failed to load connectors. Please try again.
        </p>
      )}

      {!isLoading && !isError && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard label="Total Connectors" value={total} accent="primary" />
            <StatCard label="Active" value={active} accent="success" delay={40} />
            <StatCard label="Documents Indexed" value={documents} accent="info" delay={80} />
          </div>

          {total === 0 ? (
            <EmptyState
              title="No connectors yet"
              description="Connect GitHub, Confluence, Jira, or Grafana to start indexing enterprise knowledge."
              action={
                <Link to="/connectors/add" className="btn-primary">
                  Add your first connector
                </Link>
              }
            />
          ) : (
            <GlassCard className="overflow-x-auto p-0" delay={120}>
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-secondary">
                    <th scope="col" className="px-4 py-3">Name</th>
                    <th scope="col" className="px-4 py-3">Type</th>
                    <th scope="col" className="px-4 py-3">Status</th>
                    <th scope="col" className="px-4 py-3">Last Sync</th>
                    <th scope="col" className="px-4 py-3">Documents</th>
                    <th scope="col" className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(connectors ?? []).map((connector) => (
                    <ConnectorRow key={connector.id} connector={connector} />
                  ))}
                </tbody>
              </table>
            </GlassCard>
          )}
        </div>
      )}
    </main>
  );
}
