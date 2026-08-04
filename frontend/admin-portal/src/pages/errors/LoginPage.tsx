import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  CheckCircledIcon,
  ExclamationTriangleIcon,
  EyeClosedIcon,
  EyeOpenIcon,
  LockClosedIcon,
  PersonIcon,
} from "@radix-ui/react-icons";

import { useAuth } from "../../context/AuthContext";
import { GlassCard } from "../../components/ui/GlassCard";
import { loginUser } from "../../services/authService";

/**
 * Local-dev login form — exchanges username/password for a real Keycloak JWT
 * via POST /api/auth/dev-login (src/auth/dev_login.py), a password-grant
 * route enabled only in local/dev environments (TASK-US004-01 tracks the
 * full browser-redirect OIDC flow for production).
 */
export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState(searchParams.get("username") ?? "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const justRegistered = searchParams.get("registered") === "1";

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const data = await loginUser(username, password);
      await signIn(data.access_token);
      navigate("/", { replace: true });
    } catch {
      setError("Invalid username or password.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main
      aria-label="Sign in"
      className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12"
    >
      {/* Ambient floating orbs to reinforce the mesh-gradient background */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-primary-300/30 blur-3xl animate-float-slow"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 -right-24 h-80 w-80 rounded-full bg-sky-300/25 blur-3xl animate-float-slower"
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center animate-slide-up">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 shadow-glow">
            <LockClosedIcon className="h-7 w-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">ContextIQ</h1>
          <p className="text-sm text-secondary">Admin Portal</p>
        </div>

        <GlassCard className="p-6 sm:p-8" delay={80}>
          {justRegistered && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-sm text-emerald-700 animate-slide-up">
              <CheckCircledIcon className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>Account created. Sign in with your new username and password.</span>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            <div className="mb-4">
              <label htmlFor="username" className="form-label">
                Username
              </label>
              <div className="relative">
                <PersonIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="username"
                  name="username"
                  className="input pl-9"
                  placeholder="you@contextiq.dev"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="mb-5">
              <label htmlFor="password" className="form-label">
                Password
              </label>
              <div className="relative">
                <LockClosedIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  className="input pl-9 pr-9"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-colors hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-primary-300/60 rounded"
                >
                  {showPassword ? (
                    <EyeClosedIcon className="h-4 w-4" />
                  ) : (
                    <EyeOpenIcon className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            {error && (
              <div
                role="alert"
                className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50/80 px-3 py-2 text-sm text-red-700 animate-slide-up"
              >
                <ExclamationTriangleIcon className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button type="submit" disabled={isSubmitting} className="btn-primary w-full">
              {isSubmitting ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-secondary">
            Need an account?{" "}
            <Link to="/register" className="font-semibold text-primary-700 hover:text-primary-800">
              Create one
            </Link>
          </p>
        </GlassCard>

        <p className="mt-6 text-center text-xs text-secondary">
          Local-dev sign-in exchanges credentials for a Keycloak-issued session.
        </p>
      </div>
    </main>
  );
}
