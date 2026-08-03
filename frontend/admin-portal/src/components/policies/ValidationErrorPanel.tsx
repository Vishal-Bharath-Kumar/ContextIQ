interface Props {
  errors: string[];
  isLoading: boolean;
}

export function ValidationErrorPanel({ errors, isLoading }: Props) {
  if (isLoading) {
    return (
      <p role="status" aria-live="polite" className="text-xs text-gray-400 mt-1">
        Validating…
      </p>
    );
  }

  if (errors.length === 0) {
    return (
      <p role="status" aria-live="polite" className="text-xs text-green-700 mt-1">
        ✓ Valid Rego
      </p>
    );
  }

  return (
    <ul
      role="alert"
      aria-label="Rego validation errors"
      className="mt-2 space-y-1"
    >
      {errors.map((err, i) => (
        <li key={i} className="text-xs text-red-600 font-mono bg-red-50 px-2 py-1 rounded">
          {err}
        </li>
      ))}
    </ul>
  );
}
