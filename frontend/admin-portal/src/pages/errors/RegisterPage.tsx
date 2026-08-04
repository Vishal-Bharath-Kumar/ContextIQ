import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import axios from "axios";
import {
  ExclamationTriangleIcon,
  LockClosedIcon,
  PersonIcon,
} from "@radix-ui/react-icons";

import { GlassCard } from "../../components/ui/GlassCard";
import { registerSchema, type RegisterFields } from "../../schemas/registerSchema";
import { registerUser } from "../../services/authService";

export function RegisterPage() {
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const roleOptions = [
    { value: "admin", label: "Admin" },
    { value: "developer", label: "Developer" },
    { value: "platform_engineer", label: "Platform Engineer" },
  ] as const;

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterFields>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      first_name: "",
      last_name: "",
      username: "",
      email: "",
      password: "",
      confirm_password: "",
      role: "developer",
    },
  });

  async function onSubmit(raw: RegisterFields): Promise<void> {
    setServerError(null);
    setIsSubmitting(true);
    try {
      const data = registerSchema.parse(raw);
      await registerUser({
        username: data.username,
        email: data.email,
        first_name: data.first_name,
        last_name: data.last_name,
        password: data.password,
        role: data.role,
      });
      navigate(`/login?registered=1&username=${encodeURIComponent(data.username)}`, {
        replace: true,
      });
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setServerError("A user with this username or email already exists.");
      } else if (axios.isAxiosError(err) && typeof err.response?.data?.detail === "string") {
        setServerError(err.response.data.detail);
      } else {
        setServerError("Unable to create your account right now. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main
      aria-label="Register"
      className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-primary-300/30 blur-3xl animate-float-slow"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-24 -right-24 h-80 w-80 rounded-full bg-sky-300/25 blur-3xl animate-float-slower"
      />

      <div className="relative w-full max-w-lg">
        <div className="mb-8 flex flex-col items-center text-center animate-slide-up">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 shadow-glow">
            <LockClosedIcon className="h-7 w-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Create account</h1>
          <p className="text-sm text-secondary">Choose a local-dev role for this ContextIQ account</p>
        </div>

        <GlassCard className="p-6 sm:p-8" delay={80}>
          {serverError && (
            <div
              role="alert"
              className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50/80 px-3 py-2 text-sm text-red-700 animate-slide-up"
            >
              <ExclamationTriangleIcon className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>{serverError}</span>
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="first_name" className="form-label">
                  First name
                </label>
                <input id="first_name" className="input" {...register("first_name")} />
                {errors.first_name && (
                  <p className="mt-1 text-xs text-red-600">{errors.first_name.message}</p>
                )}
              </div>

              <div>
                <label htmlFor="last_name" className="form-label">
                  Last name
                </label>
                <input id="last_name" className="input" {...register("last_name")} />
                {errors.last_name && (
                  <p className="mt-1 text-xs text-red-600">{errors.last_name.message}</p>
                )}
              </div>
            </div>

            <div>
              <label htmlFor="username" className="form-label">
                Username
              </label>
              <div className="relative">
                <PersonIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="username"
                  className="input pl-9"
                  autoComplete="username"
                  {...register("username")}
                />
              </div>
              {errors.username && (
                <p className="mt-1 text-xs text-red-600">{errors.username.message}</p>
              )}
            </div>

            <div>
              <label htmlFor="email" className="form-label">
                Email
              </label>
              <input id="email" type="email" className="input" autoComplete="email" {...register("email")} />
              {errors.email && <p className="mt-1 text-xs text-red-600">{errors.email.message}</p>}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="password" className="form-label">
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  {...register("password")}
                />
                {errors.password && (
                  <p className="mt-1 text-xs text-red-600">{errors.password.message}</p>
                )}
              </div>

              <div>
                <label htmlFor="confirm_password" className="form-label">
                  Confirm password
                </label>
                <input
                  id="confirm_password"
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  {...register("confirm_password")}
                />
                {errors.confirm_password && (
                  <p className="mt-1 text-xs text-red-600">{errors.confirm_password.message}</p>
                )}
              </div>
            </div>

            <div>
              <label htmlFor="role" className="form-label">
                User role
              </label>
              <select id="role" className="input" {...register("role")}>
                {roleOptions.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
              {errors.role && <p className="mt-1 text-xs text-red-600">{errors.role.message}</p>}
            </div>

            <button type="submit" disabled={isSubmitting} className="btn-primary w-full">
              {isSubmitting ? "Creating account…" : "Create account"}
            </button>
          </form>
        </GlassCard>

        <p className="mt-6 text-center text-sm text-secondary">
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-primary-700 hover:text-primary-800">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}