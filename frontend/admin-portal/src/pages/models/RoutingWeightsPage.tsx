import { useRoutingWeights } from "../../services/routingWeightService";
import { IntentWeightCard } from "../../components/models/IntentWeightCard";
import { PageHeader } from "../../components/ui/PageHeader";

export function RoutingWeightsPage() {
  const { data: entries, isLoading, isError } = useRoutingWeights();

  return (
    <main aria-labelledby="routing-weights-heading" className="page-layout">
      <PageHeader
        headingId="routing-weights-heading"
        title="Dynamic Model Routing"
        subtitle="Tune quality, cost, and latency weights per intent to steer the model router."
      />

      {isLoading && (
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading routing weights…
        </p>
      )}

      {isError && (
        <p role="alert" className="text-red-600 py-4">
          Failed to load routing weights. Please try again.
        </p>
      )}

      {!isLoading && !isError && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(entries ?? []).map((entry, i) => (
            <div key={entry.intent_type} className="stagger-item" style={{ animationDelay: `${i * 50}ms` }}>
              <IntentWeightCard entry={entry} />
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
