import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import type { AuditLogFilters } from "../../services/auditLogService";

const filterSchema = z.object({
  user:          z.string().optional(),
  action:        z.string().optional(),
  resource_type: z.string().optional(),
  resource_id:   z.string().optional(),
  date_from:     z.string().optional(),
  date_to:       z.string().optional(),
});

type FilterFormValues = z.infer<typeof filterSchema>;

interface Props {
  onFilter: (filters: AuditLogFilters) => void;
}

export function AuditLogFilterBar({ onFilter }: Props) {
  const { register, handleSubmit, reset } = useForm<FilterFormValues>({
    resolver: zodResolver(filterSchema),
  });

  function handleClear(): void {
    reset();
    onFilter({});
  }

  return (
    <form
      onSubmit={handleSubmit(onFilter)}
      aria-label="Audit log filters"
      className="flex flex-wrap gap-2 p-4 bg-surface-subtle rounded-lg"
    >
      <input
        {...register("user")}
        placeholder="User ID"
        aria-label="Filter by user ID"
        className="input"
      />
      <input
        {...register("action")}
        placeholder="Action (e.g. policy.created)"
        aria-label="Filter by action"
        className="input"
      />
      <input
        {...register("resource_type")}
        placeholder="Resource type"
        aria-label="Filter by resource type"
        className="input"
      />
      <input
        {...register("resource_id")}
        placeholder="Resource ID"
        aria-label="Filter by resource ID"
        className="input"
      />
      <input
        {...register("date_from")}
        type="datetime-local"
        aria-label="From date"
        className="input"
      />
      <input
        {...register("date_to")}
        type="datetime-local"
        aria-label="To date"
        className="input"
      />
      <button type="submit" className="btn-primary">Apply</button>
      <button type="button" onClick={handleClear} className="btn-secondary">
        Clear
      </button>
    </form>
  );
}
