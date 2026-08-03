import { Link } from "react-router-dom";

export function ForbiddenPage() {
  return (
    <main
      className="flex flex-col items-center justify-center min-h-screen gap-4"
      aria-labelledby="forbidden-heading"
    >
      <h1 id="forbidden-heading" className="text-3xl font-bold text-gray-800">
        403 — Access Denied
      </h1>
      <p className="text-gray-500 text-sm">
        You do not have the role required to view this page.
        Contact your administrator to request access.
      </p>
      <Link to="/" className="btn-secondary text-sm" aria-label="Go to home page">
        Go Home
      </Link>
    </main>
  );
}
