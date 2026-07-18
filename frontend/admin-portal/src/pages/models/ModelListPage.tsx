import { useModels } from "../../services/modelService";
import { ModelRow } from "../../components/models/ModelRow";

export function ModelListPage() {
  const { data: models, isLoading, isError } = useModels();

  if (isLoading) {
    return <div role="status" aria-label="Loading models">Loading…</div>;
  }
  if (isError) {
    return <div role="alert">Failed to load models.</div>;
  }

  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Models</h1>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-gray-500 text-xs uppercase">
            <th className="px-4 py-2">Model ID</th>
            <th className="px-4 py-2">Provider</th>
            <th className="px-4 py-2">Context Window</th>
            <th className="px-4 py-2">Cost / 1k</th>
            <th className="px-4 py-2">Latency</th>
            <th className="px-4 py-2">Capabilities</th>
            <th className="px-4 py-2">Active</th>
          </tr>
        </thead>
        <tbody>
          {(models ?? []).map((model) => (
            <ModelRow key={model.id} model={model} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
