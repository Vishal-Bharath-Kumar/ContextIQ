import { useEffect } from "react";

/**
 * Login redirect stub — triggers the Keycloak OIDC flow (TASK-US004-01).
 * The actual token exchange is handled server-side; this page simply
 * redirects the browser to the auth endpoint.
 */
export function LoginPage() {
  useEffect(() => {
    window.location.href = "/api/auth/login";
  }, []);

  return (
    <main aria-label="Redirecting to login">
      <p>Redirecting to login&hellip;</p>
    </main>
  );
}
