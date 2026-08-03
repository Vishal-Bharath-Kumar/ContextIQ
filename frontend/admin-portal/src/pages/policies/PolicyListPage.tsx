import { Link } from "react-router-dom";
import { PlusIcon } from "@radix-ui/react-icons";

import { usePolicies } from "../../services/policyService";
import { PolicyActiveBadge } from "../../components/policies/PolicyActiveBadge";
import { PolicyVersionRow } from "../../components/policies/PolicyVersionRow";
import { ActivatePolicyDialog } from "../../components/policies/ActivatePolicyDialog";
import { DeactivatePolicyDialog } from "../../components/policies/DeactivatePolicyDialog";
import { DeletePolicyDialog } from "../../components/policies/DeletePolicyDialog";
import { PageHeader } from "../../components/ui/PageHeader";
import { GlassCard } from "../../components/ui/GlassCard";
import { EmptyState } from "../../components/ui/EmptyState";

export function PolicyListPage() {
  const { data: policies, isLoading, isError } = usePolicies();

  // Sort policies by latest creation date (newest first)
  const sortedPolicies = policies
    ? [...policies].sort((a, b) => {
        const aLatestCreated = a.versions[0]?.created_at || '';
        const bLatestCreated = b.versions[0]?.created_at || '';
        return new Date(bLatestCreated).getTime() - new Date(aLatestCreated).getTime();
      })
    : [];

  return (
    <main aria-labelledby="policies-heading" className="page-layout">
      <PageHeader
        headingId="policies-heading"
        title="Policies"
        subtitle="Govern AI context access with versioned, auditable OPA/Rego policies."
        actions={
          <Link to="/policies/new" className="btn-primary">
            <PlusIcon aria-hidden="true" />
            New Policy
          </Link>
        }
      />

      {isLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading policies…
        </p>
      )}

      {isError && (
        <p role="alert" className="text-red-600 py-4">
          Failed to load policies. Please try again.
        </p>
      )}

      {!isLoading && !isError && (policies?.length ?? 0) === 0 && (
        <EmptyState
          title="No policies defined yet"
          description="Create your first governance policy to control how AI assistants access enterprise context."
          action={
            <Link to="/policies/new" className="btn-primary">
              Create a policy
            </Link>
          }
        />
      )}

      <div className="space-y-5">
        {sortedPolicies.map((policy, i) => {
          const isActive = policy.active_version !== null;
          const canDelete = !isActive && policy.versions.some(v => 
            v.status === "draft" || v.status === "superseded"
          );
          
          return (
            <GlassCard key={policy.id} className="p-5" delay={i * 60}>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <h2 className="text-base font-semibold text-slate-900">{policy.name}</h2>
                  {policy.active_version && <PolicyActiveBadge version={policy.active_version} />}
                </div>
                <div className="flex items-center gap-2">
                  {isActive ? (
                    <DeactivatePolicyDialog policyId={policy.id} policyName={policy.name} />
                  ) : (
                    <ActivatePolicyDialog policyId={policy.id} policyName={policy.name} />
                  )}
                  <Link to={`/policies/${policy.id}`} className="btn-secondary">
                    Edit
                  </Link>
                  {canDelete && (
                    <DeletePolicyDialog 
                      policyId={policy.id} 
                      policyVersion={policy.versions[0]?.version ?? ""}
                      policyStatus={policy.versions[0]?.status ?? "draft"}
                    />
                  )}
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-secondary">
                      <th scope="col" className="px-4 py-2">Version</th>
                      <th scope="col" className="px-4 py-2">Status</th>
                      <th scope="col" className="px-4 py-2">Author</th>
                      <th scope="col" className="px-4 py-2">Activated</th>
                      {/* <th scope="col" className="px-4 py-2">Actions</th> */}
                    </tr>
                  </thead>
                  <tbody>
                    {policy.versions.map((version) => (
                      <PolicyVersionRow key={version.id} version={version} />
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          );
        })}
      </div>
    </main>
  );
}
