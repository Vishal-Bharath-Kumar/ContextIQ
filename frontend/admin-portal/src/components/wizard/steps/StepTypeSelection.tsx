import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  typeSchema,
  type TypeFields,
} from "../../../schemas/connectorWizard";
import type { ConnectorCreatePayload } from "../../../schemas/connectorWizard";

interface Props {
  defaults: Partial<ConnectorCreatePayload>;
  onNext: (data: TypeFields) => void;
}

const CONNECTOR_TYPES: {
  value: TypeFields["connector_type"];
  label: string;
  description: string;
}[] = [
  {
    value: "github",
    label: "GitHub",
    description: "Index repositories and pull requests",
  },
  {
    value: "confluence",
    label: "Confluence",
    description: "Index spaces and pages",
  },
  {
    value: "jira",
    label: "Jira",
    description: "Index projects and issues",
  },
  {
    value: "grafana",
    label: "Grafana",
    description: "Index dashboards and data sources",
  },
];

export function StepTypeSelection({ defaults, onNext }: Props) {
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<TypeFields>({
    resolver: zodResolver(typeSchema),
    defaultValues: {
      connector_type: defaults.connector_type,
      name: defaults.name ?? "",
    },
  });

  const selectedType = watch("connector_type");

  return (
    <form onSubmit={handleSubmit(onNext)} noValidate>
      <fieldset>
        <legend className="text-lg font-medium mb-4">Connector Type</legend>

        <div
          className="grid grid-cols-2 gap-3 mb-6"
          role="group"
          aria-label="Select connector type"
        >
          {CONNECTOR_TYPES.map(({ value, label, description }) => (
            <label
              key={value}
              className={`flex flex-col gap-1 p-4 rounded border-2 cursor-pointer transition-colors ${
                selectedType === value
                  ? "border-blue-600 bg-blue-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
            >
              <input
                type="radio"
                value={value}
                className="sr-only"
                aria-label={label}
                {...register("connector_type")}
              />
              <span className="font-medium text-sm">{label}</span>
              <span className="text-xs text-gray-500">{description}</span>
            </label>
          ))}
        </div>
        {errors.connector_type && (
          <p role="alert" className="text-red-600 text-xs mb-4">
            {errors.connector_type.message}
          </p>
        )}

        <label
          htmlFor="connector_name"
          className="block text-sm font-medium mb-1"
        >
          Connector name <span aria-hidden="true">*</span>
        </label>
        <input
          id="connector_name"
          type="text"
          aria-required="true"
          aria-describedby={errors.name ? "name_error" : undefined}
          className="input-field w-full"
          placeholder="e.g. my-github-connector"
          {...register("name")}
        />
        {errors.name && (
          <p id="name_error" role="alert" className="text-red-600 text-xs mt-1">
            {errors.name.message}
          </p>
        )}
      </fieldset>

      <div className="flex gap-3 mt-6">
        <button type="submit" className="btn-primary">
          Next
        </button>
      </div>
    </form>
  );
}
