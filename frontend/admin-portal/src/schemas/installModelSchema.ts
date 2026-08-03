import { z } from "zod";

export const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "google",
  "azure_openai",
  "ollama",
  "huggingface",
  "custom",
] as const;

export type ProviderType = (typeof PROVIDER_TYPES)[number];

export const installModelSchema = z.discriminatedUnion("provider_type", [
  // Ollama models
  z.object({
    provider_type: z.literal("ollama"),
    model_id: z.string().min(1, "Model ID is required").max(128),
    display_name: z.string().min(1, "Display name is required").max(128),
    ollama_model_name: z.string().min(1, "Ollama model name is required"),
    auto_pull: z.boolean().default(true),
    context_window: z.coerce.number().int().positive().optional(),
  }),
  // API-based models
  z.object({
    provider_type: z.enum(["openai", "anthropic", "google", "huggingface", "custom"]),
    model_id: z.string().min(1, "Model ID is required").max(128),
    display_name: z.string().min(1, "Display name is required").max(128),
    api_key: z.string().min(1, "API key is required"),
    api_base: z.string().url("Must be a valid URL").optional().or(z.literal("")),
    context_window: z.coerce.number().int().positive("Must be a positive integer"),
    cost_per_1k_tokens: z.coerce.number().min(0, "Cost cannot be negative").default(0),
  }),
  // Azure OpenAI
  z.object({
    provider_type: z.literal("azure_openai"),
    model_id: z.string().min(1, "Model ID is required").max(128),
    display_name: z.string().min(1, "Display name is required").max(128),
    api_key: z.string().min(1, "API key is required"),
    api_base: z.string().url("Must be a valid URL").min(1, "API base URL is required"),
    api_version: z.string().min(1, "API version is required"),
    deployment_name: z.string().min(1, "Deployment name is required"),
    context_window: z.coerce.number().int().positive("Must be a positive integer"),
    cost_per_1k_tokens: z.coerce.number().min(0, "Cost cannot be negative").default(0),
  }),
]);

export type InstallModelFields = z.infer<typeof installModelSchema>;
export type InstallModelInput = z.input<typeof installModelSchema>;

export const ollamaPullSchema = z.object({
  model_name: z.string().min(1, "Model name is required"),
});

export type OllamaPullFields = z.infer<typeof ollamaPullSchema>;
