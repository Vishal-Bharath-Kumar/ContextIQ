import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  BarChartIcon,
  CardStackIcon,
  CheckCircledIcon,
  ClipboardIcon,
  Cross1Icon,
  DashboardIcon,
  ExitIcon,
  HamburgerMenuIcon,
  LockClosedIcon,
  MixerHorizontalIcon,
  Share2Icon,
  WidthIcon,
} from "@radix-ui/react-icons";

import { useAuth } from "../context/AuthContext";
import { PlatformRole } from "../auth/roles";
import type { PlatformRoleValue } from "../auth/roles";

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
  roles: PlatformRoleValue[];
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    to: "/",
    label: "Dashboard",
    icon: <DashboardIcon aria-hidden="true" />,
    roles: [
      PlatformRole.DEVELOPER,
      PlatformRole.PLATFORM_ENGINEER,
      PlatformRole.DEVOPS_SRE,
      PlatformRole.ADMIN,
      PlatformRole.SECURITY_OFFICER,
      PlatformRole.MANAGER,
      PlatformRole.AUDITOR,
    ],
    end: true,
  },
  {
    to: "/connectors",
    label: "Connectors",
    icon: <Share2Icon aria-hidden="true" />,
    roles: [PlatformRole.PLATFORM_ENGINEER, PlatformRole.ADMIN],
  },
  {
    to: "/models",
    label: "Models",
    icon: <CardStackIcon aria-hidden="true" />,
    roles: [PlatformRole.PLATFORM_ENGINEER, PlatformRole.ADMIN],
    end: true,
  },
  {
    to: "/models/weights",
    label: "Routing Weights",
    icon: <MixerHorizontalIcon aria-hidden="true" />,
    roles: [PlatformRole.PLATFORM_ENGINEER, PlatformRole.ADMIN],
  },
  {
    to: "/tools",
    label: "Tool Registry",
    icon: <WidthIcon aria-hidden="true" />,
    roles: [PlatformRole.PLATFORM_ENGINEER, PlatformRole.ADMIN],
  },
  {
    to: "/policies",
    label: "Policies",
    icon: <LockClosedIcon aria-hidden="true" />,
    roles: [PlatformRole.SECURITY_OFFICER, PlatformRole.ADMIN],
  },
  {
    to: "/governance",
    label: "Governance",
    icon: <CheckCircledIcon aria-hidden="true" />,
    roles: [PlatformRole.SECURITY_OFFICER, PlatformRole.ADMIN],
  },
  {
    to: "/traces",
    label: "Replay Explorer",
    icon: <BarChartIcon aria-hidden="true" />,
    roles: [
      PlatformRole.AUDITOR,
      PlatformRole.DEVOPS_SRE,
      PlatformRole.SECURITY_OFFICER,
      PlatformRole.ADMIN,
    ],
  },
  {
    to: "/audit-log",
    label: "Audit Log",
    icon: <ClipboardIcon aria-hidden="true" />,
    roles: [
      PlatformRole.AUDITOR,
      PlatformRole.DEVOPS_SRE,
      PlatformRole.SECURITY_OFFICER,
      PlatformRole.ADMIN,
    ],
  },
];

function initialsOf(name?: string, email?: string): string {
  const source = name?.trim() || email?.trim() || "?";
  const parts = source.split(/[\s@.]+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function AdminLayout() {
  const { user, hasAnyRole, signOut } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  const visibleItems = NAV_ITEMS.filter((item) => hasAnyRole(item.roles));

  return (
    <div className="relative min-h-screen">
      {/* Decorative ambient glass blobs */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-24 -top-24 h-96 w-96 rounded-full bg-primary-400/25 blur-3xl animate-float-slow" />
        <div className="absolute right-0 top-1/3 h-80 w-80 rounded-full bg-sky-400/20 blur-3xl animate-float-slower" />
        <div className="absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-emerald-400/15 blur-3xl animate-float-slow" />
      </div>

      <div className="flex min-h-screen">
        {/* ── Sidebar ─────────────────────────────────────────────────── */}
        <aside
          className={`fixed inset-y-0 left-0 z-40 w-64 shrink-0 transform border-r border-border bg-surface
            shadow-glass backdrop-blur-2xl transition-transform duration-300 lg:static lg:translate-x-0
            ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
          aria-label="Main navigation"
        >
          <div className="flex h-16 items-center gap-2 border-b border-border px-5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700 text-sm font-bold text-white shadow-glow-sm">
              CQ
            </div>
            <div className="leading-tight">
              <p className="text-sm font-bold text-slate-900">ContextIQ</p>
              <p className="text-[11px] text-secondary">Admin Portal</p>
            </div>
            <button
              type="button"
              className="ml-auto rounded-md p-1 text-secondary hover:bg-white/60 lg:hidden"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation menu"
            >
              <Cross1Icon />
            </button>
          </div>

          <nav className="flex flex-col gap-1 px-3 py-4" aria-label="Primary">
            {visibleItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-gradient-to-r from-primary-500 to-primary-600 text-white shadow-glow-sm"
                      : "text-slate-600 hover:bg-white/60 hover:text-slate-900"
                  }`
                }
              >
                <span className="text-base">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="absolute inset-x-0 bottom-0 border-t border-border p-4">
            <button
              type="button"
              onClick={signOut}
              className="btn-ghost w-full justify-start gap-2 text-red-600 hover:bg-red-50/60"
            >
              <ExitIcon aria-hidden="true" />
              Sign out
            </button>
          </div>
        </aside>

        {/* Mobile overlay */}
        {mobileOpen && (
          <div
            className="fixed inset-0 z-30 bg-slate-900/30 backdrop-blur-sm lg:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
        )}

        {/* ── Main column ─────────────────────────────────────────────── */}
        <div className="flex min-w-0 flex-1 flex-col lg:pl-0">
          {/* Topbar */}
          <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-border bg-surface px-4 shadow-glass backdrop-blur-xl sm:px-6">
            <button
              type="button"
              className="rounded-md p-2 text-secondary hover:bg-white/60 lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation menu"
            >
              <HamburgerMenuIcon />
            </button>

            <div className="flex-1" />

            {user && (
              <div className="flex items-center gap-3">
                <div className="hidden text-right sm:block">
                  <p className="text-sm font-semibold leading-tight text-slate-900">
                    {user.name ?? user.email}
                  </p>
                  <p className="text-[11px] capitalize leading-tight text-secondary">
                    {user.roles.join(", ").replace(/_/g, " ") || "No role"}
                  </p>
                </div>
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-primary-700 text-xs font-bold text-white shadow-glow-sm"
                  aria-hidden="true"
                >
                  {initialsOf(user.name, user.email)}
                </div>
              </div>
            )}
          </header>

          {/* Routed content — child pages render their own <main> landmark */}
          <div key={location.pathname} className="flex-1 animate-fade-in">
            <Outlet />
          </div>
        </div>
      </div>
    </div>
  );
}
