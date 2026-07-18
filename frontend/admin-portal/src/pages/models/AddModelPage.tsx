import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";

import {
  addModelSchema,
  CAPABILITY_OPTIONS,
  type AddModelFields,
} from "../../schemas/addModelSchema";
import { useCreateModel } from "../../services/modelService";

export function AddModelPage() {
  const navigate = useNavigate();
  const { mutateAsync, isPending } = useCreateModel();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AddModelFields>({
    resolver: zodResolver(addModelSchema),
    defaultValues: { latency_tier: "fast", capabilities: [] },
  });

  const onSubmit = async (data: AddModelFields) => {
    setServerError(null);
    try {
      await mutateAsync(data);
      navigate("/models");
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setServerError(
          `Model '${data.model_id}' is already registered.`
        );
      } else {
        setServerError("An unexpected error occurred. Please try again.");
      }
    }
  };

  return (
    <div className="max-w-lg mx-auto py-8">
      <h1 className="text-xl font-semibold mb-6">Register Model</h1>

      {serverError && (
        <p role="alert" className="mb-4 text-red-600 text-sm">
          {serverError}
        </p>
      )}

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        {/* Model ID */}
        <div className="mb-4">
          <label htmlFor="model_id" className="block text-sm font-medium mb-1">
            Model ID
          </label>
          <input
            id="model_id"
            type="text"
            className="w-full border rounded px-3 py-2 text-sm"
            {...register("model_id")}
          />
          {errors.model_id && (
            <p className="mt-1 text-xs text-red-600">{errors.model_id.message}</p>
          )}
        </div>

        {/* Provider */}
        <div className="mb-4">
          <label htmlFor="provider" className="block text-sm font-medium mb-1">
            Provider
          </label>
          <input
            id="provider"
            type="text"
            className="w-full border rounded px-3 py-2 text-sm"
            {...register("provider")}
          />
          {errors.provider && (
            <p className="mt-1 text-xs text-red-600">{errors.provider.message}</p>
          )}
        </div>

        {/* Context window */}
        <div className="mb-4">
          <label
            htmlFor="context_window"
            className="block text-sm font-medium mb-1"
          >
            Context window
          </label>
          <input
            id="context_window"
            type="number"
            className="w-full border rounded px-3 py-2 text-sm"
            {...register("context_window")}
          />
          {errors.context_window && (
            <p className="mt-1 text-xs text-red-600">
              {errors.context_window.message}
            </p>
          )}
        </div>

        {/* Cost per 1k tokens */}
        <div className="mb-4">
          <label
            htmlFor="cost_per_1k_tokens"
            className="block text-sm font-medium mb-1"
          >
            Cost per 1k tokens
          </label>
          <input
            id="cost_per_1k_tokens"
            type="number"
            step="0.0001"
            className="w-full border rounded px-3 py-2 text-sm"
            {...register("cost_per_1k_tokens")}
          />
          {errors.cost_per_1k_tokens && (
            <p className="mt-1 text-xs text-red-600">
              {errors.cost_per_1k_tokens.message}
            </p>
          )}
        </div>

        {/* Latency tier */}
        <div className="mb-4">
          <label
            htmlFor="latency_tier"
            className="block text-sm font-medium mb-1"
          >
            Latency tier
          </label>
          <select
            id="latency_tier"
            className="w-full border rounded px-3 py-2 text-sm"
            {...register("latency_tier")}
          >
            <option value="fast">Fast</option>
            <option value="medium">Medium</option>
            <option value="slow">Slow</option>
          </select>
        </div>

        {/* Capabilities */}
        <fieldset className="mb-6">
          <legend className="text-sm font-medium mb-2">Capabilities</legend>
          <div className="grid grid-cols-2 gap-2">
            {CAPABILITY_OPTIONS.map((cap) => (
              <label key={cap} className="flex items-center gap-2 text-sm">
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
            <p className="mt-1 text-xs text-red-600">
              {errors.capabilities.message}
            </p>
          )}
        </fieldset>

        <button
          type="submit"
          disabled={isPending}
          className="btn-primary w-full"
        >
          {isPending ? "Registering…" : "Register Model"}
        </button>
      </form>
    </div>
  );
}
