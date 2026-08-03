interface Props {
  version: string;
}

export function PolicyActiveBadge({ version }: Props) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800"
      aria-label={`Active version: ${version}`}
    >
      Active v{version}
    </span>
  );
}
