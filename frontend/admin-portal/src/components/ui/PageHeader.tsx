import type { ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  headingId?: string;
}

/** Consistent glass page header: title + optional subtitle + action slot. */
export function PageHeader({ title, subtitle, actions, headingId }: Props) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between animate-slide-up">
      <div>
        <h1 id={headingId} className="page-title">
          {title}
        </h1>
        {subtitle && <p className="page-subtitle mb-0">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
