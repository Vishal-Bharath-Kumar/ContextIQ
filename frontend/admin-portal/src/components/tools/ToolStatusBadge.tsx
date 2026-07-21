interface Props {
  status: "active" | "inactive";
}

export function ToolStatusBadge({ status }: Props) {
  const isActive = status === "active";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${
        isActive ? "badge-green" : "badge-grey"
      }`}
    >
      <span
        className={`mr-1.5 h-1.5 w-1.5 rounded-full ${
          isActive ? "bg-emerald-500 animate-glow-pulse" : "bg-slate-400"
        }`}
        aria-hidden="true"
      />
      {status}
    </span>
  );
}
