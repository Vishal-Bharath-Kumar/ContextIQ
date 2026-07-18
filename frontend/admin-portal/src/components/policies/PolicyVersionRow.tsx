import { formatDistanceToNow } from "date-fns";
import { Link } from "react-router-dom";
import type { PolicyVersion } from "../../services/policyService";

const STATUS_CLASS: Record<PolicyVersion["status"], string> = {
  active: "text-green-700 font-medium",
  draft: "text-blue-600",
  superseded: "text-gray-400",
  rolled_back: "text-orange-600",
};

interface Props {
  version: PolicyVersion;
  policyId: string;
}

export function PolicyVersionRow({ version, policyId }: Props) {
  const activatedAt = version.activated_at
    ? formatDistanceToNow(new Date(version.activated_at), { addSuffix: true })
    : "—";

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="px-4 py-2">{version.version}</td>
      <td className={`px-4 py-2 capitalize ${STATUS_CLASS[version.status]}`}>
        {version.status}
      </td>
      <td className="px-4 py-2 text-gray-500">{version.author}</td>
      <td className="px-4 py-2 text-gray-500">{activatedAt}</td>
      <td className="px-4 py-2">
        <Link
          to={`/policies/${policyId}?version=${version.version}`}
          className="text-blue-600 hover:underline text-xs"
          aria-label={`Edit policy ${version.version}`}
        >
          Edit
        </Link>
      </td>
    </tr>
  );
}
