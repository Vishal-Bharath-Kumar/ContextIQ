import { z } from "zod";

// LiteLLM model ID format: "provider/model-name" OR bare "model-name"
// Examples: "gpt-4o", "anthropic/claude-3-haiku", "azure/gpt-4-turbo"
const LITELLM_MODEL_ID_REGEX = /^[a-zA-Z0-9\-_./:]+$/;

export const CAPABILITY_OPTIONS = [
  "chat",
  "completion",
  "embedding",
  "code",
  "summarization",
  "vision",
  "function_call",
] as const;

export type Capability = (typeof CAPABILITY_OPTIONS)[number];

export const addModelSchema = z.object({
  model_id: z
    .string()
    .min(1, "Model ID is required")
    .max(128)
    .regex(LITELLM_MODEL_ID_REGEX, "Use LiteLLM format: provider/model or model-name"),
  provider: z.string().min(1, "Provider is required").max(64),
  context_window: z.coerce.number().int().positive("Must be a positive integer"),
  cost_per_1k_tokens: z.coerce.number().min(0, "Cost cannot be negative"),
  latency_tier: z.enum(["fast", "medium", "slow"]),
  capabilities: z
    .array(z.enum(CAPABILITY_OPTIONS))
    .min(1, "Select at least one capability"),
});

export type AddModelFields = z.infer<typeof addModelSchema>;
export type AddModelInput = z.input<typeof addModelSchema>;
