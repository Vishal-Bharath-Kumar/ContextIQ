import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";

import {
  installModelSchema,
  PROVIDER_TYPES,
  type InstallModelInput,
  type ProviderType,
} from "../../schemas/installModelSchema";
import { useInstallModel, useOllamaModels } from "../../services/modelService";
import { GlassCard } from "../../components/ui/GlassCard";
import { PageHeader } from "../../components/ui/PageHeader";
import ModelInstallationProgressModal from "../../components/models/ModelInstallationProgressModal";

const PROVIDER_INFO: Record<
  ProviderType,
  { name: string; description: string; requiresApiKey: boolean }
> = {
  openai: {
    name: "OpenAI",
    description: "GPT-4, GPT-4o, GPT-3.5 Turbo, etc.",
    requiresApiKey: true,
  },
  anthropic: {
    name: "Anthropic",
    description: "Claude 3 (Opus, Sonnet, Haiku)",
    requiresApiKey: true,
  },
  google: {
    name: "Google",
    description: "Gemini Pro, Gemini Flash",
    requiresApiKey: true,
  },
  azure_openai: {
    name: "Azure OpenAI",
    description: "Azure-hosted OpenAI models",
    requiresApiKey: true,
  },
  ollama: {
    name: "Ollama",
    description: "Free local models (Llama, Mistral, etc.)",
    requiresApiKey: false,
  },
  huggingface: {
    name: "Hugging Face",
    description: "Open source models via Hugging Face",
    requiresApiKey: true,
  },
  custom: {
    name: "Custom",
    description: "Self-hosted or custom API endpoint",
    requiresApiKey: false,
  },
};

const POPULAR_OLLAMA_MODELS = [
  { name: "llama3.2", description: "Fast general-purpose (2GB)", context: 128000 },
  { name: "llama3.1", description: "Latest Llama 3.1 (4GB)", context: 128000 },
  { name: "mistral", description: "Fast 7B model (4GB)", context: 32768 },
  { name: "phi3", description: "Microsoft Phi-3 (2GB)", context: 128000 },
  { name: "deepseek-coder:6.7b", description: "Code generation (3GB)", context: 16384 },
  { name: "codellama", description: "Code-focused (3GB)", context: 16384 },
  { name: "gemma", description: "Google Gemma (2GB)", context: 8192 },
];

const MODEL_PRESETS: Record<string, { context: number; cost: number }> = {
  "gpt-4o": { context: 128000, cost: 0.005 },
  "gpt-4o-mini": { context: 128000, cost: 0.00015 },
  "gpt-4-turbo": { context: 128000, cost: 0.01 },
  "gpt-3.5-turbo": { context: 16385, cost: 0.0005 },
  "claude-3-opus-20240229": { context: 200000, cost: 0.015 },
  "claude-3-sonnet-20240229": { context: 200000, cost: 0.003 },
  "claude-3-haiku-20240307": { context: 200000, cost: 0.00025 },
  "gemini-pro": { context: 32768, cost: 0.00025 },
  "gemini-flash": { context: 32768, cost: 0.000125 },
};

export function InstallModelPage() {
  const navigate = useNavigate();
  const { mutateAsync, isPending } = useInstallModel();
  const { data: ollamaModels } = useOllamaModels();
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [installationJobId, setInstallationJobId] = useState<string | null>(null);
  const [installingModelId, setInstallingModelId] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
    watch,
    setValue,
  } = useForm<any>({
    resolver: zodResolver(installModelSchema),
    defaultValues: {
      provider_type: "openai",
    },
  });

  const providerType = watch("provider_type");
  const formErrors = errors as any;

  // Reset form fields when provider type changes
  useEffect(() => {
    // Clear provider-specific fields when switching providers
    const currentProvider = providerType;
    
    if (currentProvider === "ollama") {
      // Clear API-based fields
      setValue("api_key", "");
      setValue("api_base", "");
      setValue("api_version", "");
      setValue("deployment_name", "");
      setValue("cost_per_1k_tokens", 0);
      setValue("auto_pull", true);
    } else {
      // Clear Ollama-specific fields
      setValue("ollama_model_name", "");
      setValue("auto_pull", false);
    }
    
    // Clear common fields to avoid validation errors
    setValue("model_id", "");
    setValue("display_name", "");
    setValue("context_window", "");
  }, [providerType, setValue]);

  // Auto-fill context window and cost for known models
  const handleModelIdChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const id = e.target.value;
    const preset = MODEL_PRESETS[id];
    if (preset) {
      setValue("context_window", preset.context);
      setValue("cost_per_1k_tokens", preset.cost);
    }
  };

  const onSubmit = async (raw: InstallModelInput) => {
    setServerError(null);
    setSuccessMessage(null);
    try {
      const data = installModelSchema.parse(raw);
      const result = await mutateAsync(data as any);
      
      // Check if response contains job_id (background job)
      if ("job_id" in result && result.job_id) {
        setInstallationJobId(result.job_id as string);
        setInstallingModelId(result.model_id as string);
      } else {
        // Old synchronous response
        setSuccessMessage(result.message);
        setTimeout(() => navigate("/models"), 2000);
      }
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        setServerError(
          err.response?.data?.detail || "Failed to install model. Please try again."
        );
      } else {
        setServerError("An unexpected error occurred. Please try again.");
      }
    }
  };

  const providerInfo = PROVIDER_INFO[providerType as ProviderType] || PROVIDER_INFO.openai;

  return (
    <main aria-labelledby="install-model-heading" className="page-layout max-w-2xl">
      <PageHeader headingId="install-model-heading" title="Install Model" />

      <GlassCard className="p-6" delay={40}>
        {serverError && (
          <p role="alert" className="mb-4 text-red-600 text-sm">
            {serverError}
          </p>
        )}
        {successMessage && (
          <p role="status" className="mb-4 text-green-600 text-sm">
            ✓ {successMessage}
          </p>
        )}

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-6">
          {/* Provider Selection */}
          <div>
            <label htmlFor="provider_type" className="form-label">
              Provider Type
            </label>
            <select
              id="provider_type"
              className="input"
              {...register("provider_type")}
            >
              {PROVIDER_TYPES.map((type) => (
                <option key={type} value={type}>
                  {PROVIDER_INFO[type].name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-secondary">{providerInfo.description}</p>
          </div>

          {/* Ollama-specific UI */}
          {providerType === "ollama" && (
            <>
              <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                <h3 className="text-sm font-medium text-blue-900 mb-2">
                  Popular Ollama Models
                </h3>
                <div className="grid grid-cols-1 gap-2">
                  {POPULAR_OLLAMA_MODELS.map((model) => (
                    <button
                      key={model.name}
                      type="button"
                      className="text-left rounded border border-blue-200 bg-white px-3 py-2 text-sm hover:bg-blue-50 transition-colors"
                      onClick={() => {
                        setValue("ollama_model_name", model.name);
                        setValue("model_id", `ollama/${model.name}`);
                        setValue("display_name", model.name);
                        setValue("context_window", model.context);
                      }}
                    >
                      <div className="font-medium text-blue-900">{model.name}</div>
                      <div className="text-xs text-blue-700">{model.description}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label htmlFor="ollama_model_name" className="form-label">
                  Ollama Model Name
                </label>
                <input
                  id="ollama_model_name"
                  type="text"
                  className="input"
                  placeholder="llama3.2, mistral, phi3, etc."
                  {...register("ollama_model_name")}
                />
                {formErrors.ollama_model_name?.message && (
                  <p className="mt-1 text-xs text-red-600">
                    {formErrors.ollama_model_name.message}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="auto_pull"
                  {...register("auto_pull")}
                  className="rounded border-border"
                />
                <label htmlFor="auto_pull" className="text-sm">
                  Automatically download model if not available
                </label>
              </div>

              {ollamaModels && ollamaModels.length > 0 && (
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <h4 className="text-sm font-medium mb-2">
                    Downloaded Models ({ollamaModels.length})
                  </h4>
                  <div className="text-xs text-secondary space-y-1">
                    {ollamaModels.map((m) => (
                      <div key={m.digest}>{m.name}</div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* API-based provider fields */}
          {providerInfo.requiresApiKey && (
            <>
              <div>
                <label htmlFor="api_key" className="form-label">
                  API Key <span className="text-red-500">*</span>
                </label>
                <input
                  id="api_key"
                  type="password"
                  className="input font-mono"
                  placeholder="sk-..."
                  {...register("api_key")}
                />
                {formErrors.api_key?.message && (
                  <p className="mt-1 text-xs text-red-600">{formErrors.api_key.message}</p>
                )}
                <p className="mt-1 text-xs text-secondary">
                  Stored securely in HashiCorp Vault
                </p>
              </div>

              {providerType === "azure_openai" && (
                <>
                  <div>
                    <label htmlFor="api_base" className="form-label">
                      API Base URL <span className="text-red-500">*</span>
                    </label>
                    <input
                      id="api_base"
                      type="url"
                      className="input font-mono text-sm"
                      placeholder="https://your-resource.openai.azure.com"
                      {...register("api_base")}
                    />
                    {formErrors.api_base?.message && (
                      <p className="mt-1 text-xs text-red-600">{formErrors.api_base.message}</p>
                    )}
                  </div>

                  <div>
                    <label htmlFor="api_version" className="form-label">
                      API Version <span className="text-red-500">*</span>
                    </label>
                    <input
                      id="api_version"
                      type="text"
                      className="input"
                      placeholder="2024-02-15-preview"
                      {...register("api_version")}
                    />
                    {formErrors.api_version?.message && (
                      <p className="mt-1 text-xs text-red-600">
                        {formErrors.api_version.message}
                      </p>
                    )}
                  </div>

                  <div>
                    <label htmlFor="deployment_name" className="form-label">
                      Deployment Name <span className="text-red-500">*</span>
                    </label>
                    <input
                      id="deployment_name"
                      type="text"
                      className="input"
                      placeholder="gpt-4o-deployment"
                      {...register("deployment_name")}
                    />
                    {formErrors.deployment_name?.message && (
                      <p className="mt-1 text-xs text-red-600">
                        {formErrors.deployment_name.message}
                      </p>
                    )}
                  </div>
                </>
              )}

              {providerType !== "azure_openai" && (
                <div>
                  <label htmlFor="api_base" className="form-label">
                    API Base URL (optional)
                  </label>
                  <input
                    id="api_base"
                    type="url"
                    className="input font-mono text-sm"
                    placeholder="Leave empty for default"
                    {...register("api_base")}
                  />
                  {formErrors.api_base?.message && (
                    <p className="mt-1 text-xs text-red-600">{formErrors.api_base.message}</p>
                  )}
                </div>
              )}
            </>
          )}

          {/* Common fields */}
          <div>
            <label htmlFor="model_id" className="form-label">
              Model ID <span className="text-red-500">*</span>
            </label>
            <input
              id="model_id"
              type="text"
              className="input"
              placeholder={
                providerType === "ollama"
                  ? "ollama/llama3.2"
                  : "gpt-4o-mini, claude-3-haiku-20240307, etc."
              }
              {...register("model_id")}
              onChange={handleModelIdChange}
            />
            {formErrors.model_id?.message && (
              <p className="mt-1 text-xs text-red-600">{formErrors.model_id.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="display_name" className="form-label">
              Display Name <span className="text-red-500">*</span>
            </label>
            <input
              id="display_name"
              type="text"
              className="input"
              placeholder="Friendly name for this model"
              {...register("display_name")}
            />
            {formErrors.display_name?.message && (
              <p className="mt-1 text-xs text-red-600">{formErrors.display_name.message}</p>
            )}
          </div>

          {providerType !== "ollama" && (
            <>
              <div>
                <label htmlFor="context_window" className="form-label">
                  Context Window <span className="text-red-500">*</span>
                </label>
                <input
                  id="context_window"
                  type="number"
                  className="input"
                  placeholder="128000"
                  {...register("context_window")}
                />
                {formErrors.context_window?.message && (
                  <p className="mt-1 text-xs text-red-600">
                    {formErrors.context_window.message}
                  </p>
                )}
                <p className="mt-1 text-xs text-secondary">Maximum tokens in context window</p>
              </div>

              <div>
                <label htmlFor="cost_per_1k_tokens" className="form-label">
                  Cost per 1K Tokens (USD)
                </label>
                <input
                  id="cost_per_1k_tokens"
                  type="number"
                  step="0.00001"
                  className="input"
                  placeholder="0.00015"
                  {...register("cost_per_1k_tokens")}
                />
                {formErrors.cost_per_1k_tokens?.message && (
                  <p className="mt-1 text-xs text-red-600">
                    {formErrors.cost_per_1k_tokens.message}
                  </p>
                )}
                <p className="mt-1 text-xs text-secondary">
                  Average cost for 1,000 tokens (input + output)
                </p>
              </div>
            </>
          )}

          {providerType === "ollama" && (
            <div>
              <label htmlFor="context_window_ollama" className="form-label">
                Context Window (optional)
              </label>
              <input
                id="context_window_ollama"
                type="number"
                className="input"
                placeholder="Auto-detected from model name"
                {...register("context_window")}
              />
              <p className="mt-1 text-xs text-secondary">
                Leave empty to auto-detect based on model name
              </p>
            </div>
          )}

          <div className="flex gap-3 pt-4">
            <button type="submit" disabled={isPending} className="btn-primary flex-1">
              {isPending ? "Installing…" : "Install Model"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/models")}
              className="btn-secondary"
            >
              Cancel
            </button>
          </div>
        </form>
      </GlassCard>

      {installationJobId && installingModelId && (
        <ModelInstallationProgressModal
          jobId={installationJobId}
          modelId={installingModelId}
          onClose={() => {
            setInstallationJobId(null);
            setInstallingModelId(null);
            navigate("/models");
          }}
        />
      )}
    </main>
  );
}
