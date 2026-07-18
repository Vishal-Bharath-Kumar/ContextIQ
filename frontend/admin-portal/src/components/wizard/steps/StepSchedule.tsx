import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  scheduleSchema,
  type ScheduleFields,
} from "../../../schemas/connectorWizard";

interface Props {
  defaults: Partial<ScheduleFields>;
  isPending: boolean;
  onNext: (data: ScheduleFields) => void;
  onBack: () => void;
}

const CRON_EXAMPLES = [
  { label: "Every day at 2 AM", value: "0 2 * * *" },
  { label: "Every hour", value: "@hourly" },
  { label: "Every week on Monday", value: "0 0 * * 1" },
];

export function StepSchedule({ defaults, isPending, onNext, onBack }: Props) {
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<ScheduleFields>({
    resolver: zodResolver(scheduleSchema),
    defaultValues: defaults,
  });

  return (
    <form onSubmit={handleSubmit(onNext)} noValidate>
      <fieldset>
        <legend className="text-lg font-medium mb-4">Sync Schedule</legend>

        <label
          htmlFor="sync_schedule"
          className="block text-sm font-medium mb-1"
        >
          Cron expression <span aria-hidden="true">*</span>
        </label>
        <input
          id="sync_schedule"
          type="text"
          placeholder="0 2 * * *"
          aria-required="true"
          aria-describedby={
            errors.sync_schedule ? "sync_schedule_error" : "sync_schedule_hint"
          }
          className="input-field w-full font-mono"
          {...register("sync_schedule")}
        />
        {errors.sync_schedule ? (
          <p
            id="sync_schedule_error"
            role="alert"
            className="text-red-600 text-xs mt-1"
          >
            {errors.sync_schedule.message}
          </p>
        ) : (
          <p id="sync_schedule_hint" className="text-gray-500 text-xs mt-1">
            Standard cron format or shorthand (e.g. @daily, @hourly)
          </p>
        )}

        <div className="mt-4">
          <p className="text-xs text-gray-500 mb-2">Quick select:</p>
          <div className="flex flex-wrap gap-2">
            {CRON_EXAMPLES.map(({ label, value }) => (
              <button
                key={value}
                type="button"
                onClick={() =>
                  setValue("sync_schedule", value, { shouldValidate: true })
                }
                className="btn-secondary text-xs px-3 py-1"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </fieldset>

      <div className="flex gap-3 mt-6">
        <button
          type="button"
          onClick={onBack}
          className="btn-secondary"
          disabled={isPending}
        >
          Back
        </button>
        <button type="submit" className="btn-primary" disabled={isPending}>
          {isPending ? "Saving…" : "Save Connector"}
        </button>
      </div>
    </form>
  );
}
