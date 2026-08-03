import { z } from "zod";

const NAME_REGEX = /^[a-zA-Z0-9_.\-]+$/;

/** Validates that a string is well-formed JSON representing an object. */
const jsonSchemaField = z
  .string()
  .min(1, "Input schema is required")
  .refine(
    (val) => {
      try {
        const parsed: unknown = JSON.parse(val);
        return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
      } catch {
        return false;
      }
    },
    { message: "Must be valid JSON representing an object, e.g. {\"type\": \"object\"}" },
  );

export const toolFormSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(128)
    .regex(NAME_REGEX, "Use letters, numbers, dots, dashes, or underscores only"),
  description: z.string().min(1, "Description is required"),
  version: z.string().min(1, "Version is required").max(32),
  inputSchemaText: jsonSchemaField,
});

export type ToolFormFields = z.infer<typeof toolFormSchema>;

export const DEFAULT_INPUT_SCHEMA = JSON.stringify(
  { type: "object", properties: {}, required: [] },
  null,
  2,
);
