import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";

import {
  DEFAULT_INPUT_SCHEMA,
  toolFormSchema,
  type ToolFormFields,
} from "../../schemas/toolSchema";
import { useCreateTool, useTool, useUpdateTool } from "../../services/toolRegistryService";
import { GlassCard } from "../../components/ui/GlassCard";
import { PageHeader } from "../../components/ui/PageHeader";

export function ToolFormPage() {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();
  const isEdit = Boolean(name);

  const { data: existingTool, isLoading: isLoadingTool } = useTool(name);
  const { mutateAsync: createTool, isPending: isCreating } = useCreateTool();
  const { mutateAsync: updateTool, isPending: isUpdating } = useUpdateTool();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ToolFormFields>({
    resolver: zodResolver(toolFormSchema),
    defaultValues: {
      name: "",
      description: "",
      version: "1.0.0",
      inputSchemaText: DEFAULT_INPUT_SCHEMA,
    },
  });

  useEffect(() => {
    if (existingTool) {
      reset({
        name: existingTool.name,
        description: existingTool.description,
        version: existingTool.version,
        inputSchemaText: JSON.stringify(existingTool.inputSchema, null, 2),
      });
    }
  }, [existingTool, reset]);

  const isPending = isCreating || isUpdating;

  const onSubmit = async (fields: ToolFormFields) => {
    setServerError(null);
    const inputSchema = JSON.parse(fields.inputSchemaText) as Record<string, unknown>;
    try {
      if (isEdit && name) {
        await updateTool({
          name,
          payload: { description: fields.description, version: fields.version, inputSchema },
        });
      } else {
        await createTool({
          name: fields.name,
          description: fields.description,
          version: fields.version,
          inputSchema,
        });
      }
      navigate("/tools");
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setServerError("A tool with this name is already registered.");
      } else {
        setServerError("An unexpected error occurred. Please try again.");
      }
    }
  };

  if (isEdit && isLoadingTool) {
    return (
      <main className="page-layout max-w-lg">
        <p role="status" aria-live="polite" className="text-secondary py-8">
          Loading tool…
        </p>
      </main>
    );
  }

  return (
    <main aria-labelledby="tool-form-heading" className="page-layout max-w-lg">
      <PageHeader
        headingId="tool-form-heading"
        title={isEdit ? `Edit Tool: ${name}` : "Register Tool"}
        subtitle="Tool metadata is used by agents to discover and safely invoke MCP capabilities."
      />

      <GlassCard className="p-6" delay={40}>
        {serverError && (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {serverError}
          </p>
        )}

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div>
            <label htmlFor="name" className="form-label">
              Tool Name
            </label>
            <input
              id="name"
              type="text"
              className="input disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isEdit}
              {...register("name")}
            />
            {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name.message}</p>}
          </div>

          <div>
            <label htmlFor="description" className="form-label">
              Description
            </label>
            <textarea
              id="description"
              rows={3}
              className="input"
              {...register("description")}
            />
            {errors.description && (
              <p className="mt-1 text-xs text-red-600">{errors.description.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="version" className="form-label">
              Version
            </label>
            <input id="version" type="text" className="input" {...register("version")} />
            {errors.version && (
              <p className="mt-1 text-xs text-red-600">{errors.version.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="inputSchemaText" className="form-label">
              Input Schema (JSON)
            </label>
            <textarea
              id="inputSchemaText"
              rows={8}
              spellCheck={false}
              className="input font-mono text-xs"
              {...register("inputSchemaText")}
            />
            {errors.inputSchemaText && (
              <p className="mt-1 text-xs text-red-600">{errors.inputSchemaText.message}</p>
            )}
          </div>

          <button type="submit" disabled={isPending} className="btn-primary w-full">
            {isPending ? "Saving…" : isEdit ? "Save Changes" : "Register Tool"}
          </button>
        </form>
      </GlassCard>
    </main>
  );
}
