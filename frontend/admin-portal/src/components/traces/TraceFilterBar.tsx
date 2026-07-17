import { useEffect, useRef } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

export interface TraceFilters {
  user_id?:            string;
  intent?:             string;
  model_selected?:     string;
  governance_blocked?: boolean;
  from?:               string;  // ISO-8601
  to?:                 string;  // ISO-8601
}

const filterSchema = z.object({
  user_id:            z.string().optional(),
  intent:             z.string().optional(),
  model_selected:     z.string().optional(),
  governance_blocked: z.enum(["", "true", "false"]).optional(),
  from:               z.string().optional(),
  to:                 z.string().optional(),
});

type FilterFormValues = z.infer<typeof filterSchema>;

interface Props {
  onFilter: (filters: TraceFilters) => void;
}

function toFilters(values: FilterFormValues): TraceFilters {
  return {
    user_id:        values.user_id        || undefined,
    intent:         values.intent         || undefined,
    model_selected: values.model_selected || undefined,
    governance_blocked:
      values.governance_blocked === "true"  ? true  :
      values.governance_blocked === "false" ? false :
      undefined,
    from: values.from ? new Date(values.from).toISOString() : undefined,
    to:   values.to   ? new Date(values.to).toISOString()   : undefined,
  };
}

export function TraceFilterBar({ onFilter }: Props) {
  const { register, watch, reset } = useForm<FilterFormValues>({
    resolver: zodResolver(filterSchema),
    defaultValues: {
      user_id:            "",
      intent:             "",
      model_selected:     "",
      governance_blocked: "",
      from:               "",
      to:                 "",
    },
  });

  const values = watch();

  // Stable ref so the effect never needs onFilter in its dep array
  const onFilterRef = useRef(onFilter);
  useEffect(() => { onFilterRef.current = onFilter; });

  // AC-1: debounce 400 ms — no API call on every keystroke
  const userIdVal            = values.user_id;
  const intentVal            = values.intent;
  const modelVal             = values.model_selected;
  const governanceVal        = values.governance_blocked;
  const fromVal              = values.from;
  const toVal                = values.to;

  useEffect(() => {
    const timer = setTimeout(() => {
      onFilterRef.current(toFilters({
        user_id:            userIdVal,
        intent:             intentVal,
        model_selected:     modelVal,
        governance_blocked: governanceVal,
        from:               fromVal,
        to:                 toVal,
      }));
    }, 400);
    return () => clearTimeout(timer);
  }, [userIdVal, intentVal, modelVal, governanceVal, fromVal, toVal]);

  return (
    <form
      aria-label="Trace search filters"
      role="search"
      className="flex flex-wrap gap-2 p-4 bg-surface-subtle rounded-lg"
    >
      <input
        {...register("user_id")}
        placeholder="User ID"
        aria-label="Filter by user ID"
        className="input"
      />
      <input
        {...register("intent")}
        placeholder="Intent type"
        aria-label="Filter by intent type"
        className="input"
      />
      <input
        {...register("model_selected")}
        placeholder="Model"
        aria-label="Filter by model"
        className="input"
      />
      <select
        {...register("governance_blocked")}
        aria-label="Filter by governance decision"
        className="input"
      >
        <option value="">Any governance</option>
        <option value="true">Blocked</option>
        <option value="false">Allowed</option>
      </select>
      <input
        {...register("from")}
        type="datetime-local"
        aria-label="From date"
        className="input"
      />
      <input
        {...register("to")}
        type="datetime-local"
        aria-label="To date"
        className="input"
      />
      <button
        type="button"
        onClick={() => reset()}
        className="btn-secondary"
        aria-label="Clear all filters"
      >
        Clear
      </button>
    </form>
  );
}
