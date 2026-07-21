import { useState } from "react";
import * as Slider from "@radix-ui/react-slider";

import type { RoutingWeightEntry } from "../../services/routingWeightService";
import { useUpdateRoutingWeights } from "../../services/routingWeightService";

interface Props {
  entry: RoutingWeightEntry;
}

type WeightKey = "quality_weight" | "cost_weight" | "latency_weight";

const SLIDER_CONFIGS: { key: WeightKey; label: string; colour: string }[] = [
  { key: "quality_weight", label: "Quality", colour: "bg-blue-500" },
  { key: "cost_weight", label: "Cost", colour: "bg-green-500" },
  { key: "latency_weight", label: "Latency", colour: "bg-amber-500" },
];

export function IntentWeightCard({ entry }: Props) {
  const [weights, setWeights] = useState({
    quality_weight: entry.quality_weight,
    cost_weight: entry.cost_weight,
    latency_weight: entry.latency_weight,
  });
  const { mutate: save, isPending } = useUpdateRoutingWeights();

  /**
   * Re-normalise: when the user drags slider `key` to `newVal`,
   * distribute the remaining (1 - newVal) proportionally across the other two.
   */
  const handleChange = (key: WeightKey, newVal: number) => {
    const clamped = Math.max(0.05, Math.min(0.9, newVal));
    const others = SLIDER_CONFIGS.map((w) => w.key).filter((k) => k !== key);
    const sumOther = others.reduce((s, k) => s + weights[k], 0) || 0.5;
    const scale = (1 - clamped) / sumOther;

    setWeights({
      ...weights,
      [key]: clamped,
      [others[0]]: Math.round(weights[others[0]] * scale * 100) / 100,
      [others[1]]:
        Math.round((1 - clamped - weights[others[0]] * scale) * 100) / 100,
    });
  };

  const handleSave = () =>
    save({ intentType: entry.intent_type, weights });

  return (
    <div className="glass-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-medium text-sm capitalize">
          {entry.intent_type.replace(/_/g, " ")}
        </h3>
        <button
          type="button"
          onClick={handleSave}
          disabled={isPending}
          className="btn-primary text-xs"
          aria-label={`Save routing weights for ${entry.intent_type}`}
        >
          {isPending ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="space-y-4">
        {SLIDER_CONFIGS.map(({ key, label, colour }) => (
          <div key={key}>
            <div className="flex justify-between text-xs mb-1">
              <span>{label}</span>
              <span className="font-mono">
                {(weights[key] * 100).toFixed(0)}%
              </span>
            </div>
            <Slider.Root
              min={5}
              max={90}
              step={5}
              value={[Math.round(weights[key] * 100)]}
              onValueChange={([v]) => handleChange(key, v / 100)}
              aria-label={`${label} weight for ${entry.intent_type}`}
              className="relative flex items-center h-5 w-full"
            >
              <Slider.Track className="bg-gray-200 relative grow rounded-full h-1.5">
                <Slider.Range className={`absolute rounded-full h-full ${colour}`} />
              </Slider.Track>
              <Slider.Thumb
                className="block w-4 h-4 rounded-full bg-white border-2 border-gray-400 shadow
                  focus:outline-none focus:ring-2 focus:ring-blue-500"
                aria-label={`${label} weight for ${entry.intent_type}`}
              />
            </Slider.Root>
          </div>
        ))}
      </div>
    </div>
  );
}
