interface Props {
  steps: string[];
  currentStep: number;
}

export function WizardStepper({ steps, currentStep }: Props) {
  return (
    <nav aria-label="Add connector progress" className="mb-8">
      <ol className="flex gap-0" role="list">
        {steps.map((label, i) => {
          const state =
            i < currentStep
              ? "complete"
              : i === currentStep
                ? "current"
                : "upcoming";

          return (
            <li
              key={label}
              aria-current={state === "current" ? "step" : undefined}
              className={`flex-1 text-center text-sm font-medium py-2 border-b-2 ${
                state === "complete"
                  ? "border-green-500 text-green-700"
                  : state === "current"
                    ? "border-blue-600 text-blue-700"
                    : "border-gray-200 text-gray-400"
              }`}
            >
              <span className="sr-only">
                {state === "complete"
                  ? `${label} (completed)`
                  : state === "current"
                    ? `${label} (current step)`
                    : label}
              </span>
              <span aria-hidden="true">
                {i + 1}. {label}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
