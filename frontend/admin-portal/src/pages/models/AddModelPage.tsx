import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";

import {
  addModelSchema,
  CAPABILITY_OPTIONS,
  type AddModelInput,
} from "../../schemas/addModelSchema";
import { useCreateModel } from "../../services/modelService";
import { GlassCard } from "../../components/ui/GlassCard";
import { PageHeader } from "../../components/ui/PageHeader";

export function AddModelPage() {
  const navigate = useNavigate();
  const { mutateAsync, isPending } = useCreateModel();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AddModelInput>({
    resolver: zodResolver(addModelSchema),
    defaultValues: { latency_tier: "medium", capabilities: [] },
  });

  const onSubmit = async (raw: AddModelInput) => {
    setServerError(null);
    try {
      const data = addModelSchema.parse(raw);
      await mutateAsync(data);
      navigate("/models");
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setServerError("A model with this ID is already registered.");
      } else {
        setServerError("An unexpected error occurred. Please try again.");
      }
    }
  };

  return (
    <main aria-labelledby="add-model-heading" className="page-layout max-w-lg">
      <PageHeader headingId="add-model-heading" title="Register Model" />

      <GlassCard className="p-6" delay={40}>
        {serverError && (
          <p role="alert" className="mb-4 text-red-600 text-sm">
            {serverError}
          </p>
        )}

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {/* Model ID */}
          <div>
            <label htmlFor="model_id" className="form-label">
              Model ID
            </label>
            <input id="model_id" type="text" className="input" {...register("model_id")} />
            {errors.model_id && (
              <p className="mt-1 text-xs text-red-600">{errors.model_id.message}</p>
            )}
          </div>

          {/* Provider */}
          <div>
            <label htmlFor="provider" className="form-label">
              Provider
            </label>
            <input id="provider" type="text" className="input" {...register("provider")} />
            {errors.provider && (
              <p className="mt-1 text-xs text-red-600">{errors.provider.message}</p>
            )}
          </div>

          {/* Context window */}
          <div>
            <label htmlFor="context_window" className="form-label">
              Context window
            </label>
            <input
              id="context_window"
              type="number"
              className="input"
              {...register("context_window")}
            />
            {errors.context_window && (
              <p className="mt-1 text-xs text-red-600">{errors.context_window.message}</p>
            )}
          </div>

          {/* Cost per 1k tokens */}
          <div>
            <label htmlFor="cost_per_1k_tokens" className="form-label">
              Cost per 1k tokens
            </label>
            <input
              id="cost_per_1k_tokens"
              type="number"
              step="0.0001"
              className="input"
              {...register("cost_per_1k_tokens")}
            />
            {errors.cost_per_1k_tokens && (
              <p className="mt-1 text-xs text-red-600">{errors.cost_per_1k_tokens.message}</p>
            )}
          </div>

          {/* Latency tier */}
          <div>
            <label htmlFor="latency_tier" className="form-label">
              Latency tier
            </label>
            <select id="latency_tier" className="input" {...register("latency_tier")}>
              <option value="fast">Fast</option>
              <option value="medium">Medium</option>
              <option value="slow">Slow</option>
            </select>
          </div>

          {/* Capabilities */}
          <fieldset>
            <legend className="form-label">Capabilities</legend>
            <div className="grid grid-cols-2 gap-2">
              {CAPABILITY_OPTIONS.map((cap) => (
                <label
                  key={cap}
                  className="flex items-center gap-2 rounded-lg border border-border bg-white/50 px-2.5 py-1.5 text-sm transition-colors hover:bg-white/80"
                >
                  <input
                    type="checkbox"
                    value={cap}
                    aria-label={cap}
                    {...register("capabilities")}
                  />
                  {cap}
                </label>
              ))}
            </div>
            {errors.capabilities && (
              <p className="mt-1 text-xs text-red-600">{errors.capabilities.message}</p>
            )}
          </fieldset>

          <button type="submit" disabled={isPending} className="btn-primary w-full">
            {isPending ? "Registering…" : "Register Model"}
          </button>
        </form>
      </GlassCard>
    </main>
  );
}
