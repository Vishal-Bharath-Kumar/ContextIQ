import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";

import { useAuth } from "../../context/AuthContext";

/**
 * Local-dev login form — exchanges username/password for a real Keycloak JWT
 * via POST /api/auth/dev-login (src/auth/dev_login.py), a password-grant
 * route enabled only in local/dev environments (TASK-US004-01 tracks the
 * full browser-redirect OIDC flow for production).
 */
export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const { data } = await axios.post<{ access_token: string }>(
        `${import.meta.env.VITE_API_BASE_URL ?? "/api"}/auth/dev-login`,
        { username, password },
      );
      await signIn(data.access_token);
      navigate("/", { replace: true });
    } catch {
      setError("Invalid username or password.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main aria-label="Sign in" style={{ maxWidth: 320, margin: "4rem auto" }}>
      <h1>ContextIQ Admin Portal</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
