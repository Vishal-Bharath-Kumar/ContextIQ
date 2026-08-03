import type { RouteObject } from "react-router-dom";

import { PlatformRole } from "../auth/roles";
import { AdminLayout } from "../layouts/AdminLayout";
import {
  RequireAuditor,
  RequirePlatformEngineer,
  RequireRoles,
  RequireSecurityOfficer,
} from "../guards";
import { AddConnectorPage } from "../pages/connectors/AddConnectorPage";
import { ConnectorListPage } from "../pages/connectors/ConnectorListPage";
import { ForbiddenPage } from "../pages/errors/ForbiddenPage";
import { LoginPage } from "../pages/errors/LoginPage";
import { AddModelPage } from "../pages/models/AddModelPage";
import { InstallModelPage } from "../pages/models/InstallModelPage";
import { ModelListPage } from "../pages/models/ModelListPage";
import { RoutingWeightsPage } from "../pages/models/RoutingWeightsPage";
import { PolicyDetailPage } from "../pages/policies/PolicyDetailPage";
import { PolicyListPage } from "../pages/policies/PolicyListPage";
import { GovernanceSettingsPage } from "../pages/governance/GovernanceSettingsPage";
import { ReplayExplorerPage } from "../pages/traces/ReplayExplorerPage";
import { TraceDetailPage } from "../pages/traces/TraceDetailPage";
import { ToolFormPage } from "../pages/tools/ToolFormPage";
import { ToolRegistryListPage } from "../pages/tools/ToolRegistryListPage";
import { AuditLogPage } from "../pages/AuditLogPage";
import { DashboardPage } from "../pages/DashboardPage";

export const ADMIN_ROUTES: RouteObject[] = [
  // Public routes — must NOT sit under the guarded "/" parent below, otherwise
  // an unauthenticated visit to any path (including /login itself) triggers
  // an infinite redirect loop: guard -> Navigate to /login -> re-matches the
  // same guarded parent -> guard -> Navigate to /login -> ... (blank screen).
  { path: "/login", element: <LoginPage /> },
  { path: "/403", element: <ForbiddenPage /> },
  {
    path: "/",
    element: (
      // Root requires any authenticated user with at least one valid platform role.
      <RequireRoles
        allowedRoles={[
          PlatformRole.DEVELOPER,
          PlatformRole.PLATFORM_ENGINEER,
          PlatformRole.DEVOPS_SRE,
          PlatformRole.ADMIN,
          PlatformRole.SECURITY_OFFICER,
          PlatformRole.MANAGER,
          PlatformRole.AUDITOR,
        ]}
      >
        <AdminLayout />
      </RequireRoles>
    ),
    children: [
      { index: true, element: <DashboardPage /> },

      // Connectors — PLATFORM_ENGINEER or ADMIN
      {
        path: "connectors",
        element: (
          <RequirePlatformEngineer>
            <ConnectorListPage />
          </RequirePlatformEngineer>
        ),
      },
      {
        path: "connectors/add",
        element: (
          <RequirePlatformEngineer>
            <AddConnectorPage />
          </RequirePlatformEngineer>
        ),
      },

      // Policies — SECURITY_OFFICER or ADMIN
      {
        path: "policies",
        element: (
          <RequireSecurityOfficer>
            <PolicyListPage />
          </RequireSecurityOfficer>
        ),
      },
      {
        path: "policies/:id",
        element: (
          <RequireSecurityOfficer>
            <PolicyDetailPage />
          </RequireSecurityOfficer>
        ),
      },
      {
        path: "policies/new",
        element: (
          <RequireSecurityOfficer>
            <PolicyDetailPage />
          </RequireSecurityOfficer>
        ),
      },

      // Governance Settings — SECURITY_OFFICER or ADMIN
      {
        path: "governance",
        element: (
          <RequireSecurityOfficer>
            <GovernanceSettingsPage />
          </RequireSecurityOfficer>
        ),
      },

      // Models — PLATFORM_ENGINEER or ADMIN
      {
        path: "models",
        element: (
          <RequirePlatformEngineer>
            <ModelListPage />
          </RequirePlatformEngineer>
        ),
      },
      {
        path: "models/add",
        element: (
          <RequirePlatformEngineer>
            <AddModelPage />
          </RequirePlatformEngineer>
        ),
      },
      {
        path: "models/install",
        element: (
          <RequirePlatformEngineer>
            <InstallModelPage />
          </RequirePlatformEngineer>
        ),
      },
      {
        path: "models/weights",
        element: (
          <RequirePlatformEngineer>
            <RoutingWeightsPage />
          </RequirePlatformEngineer>
        ),
      },

      // Tool Registry — PLATFORM_ENGINEER or ADMIN
      {
        path: "tools",
        element: (
          <RequirePlatformEngineer>
            <ToolRegistryListPage />
          </RequirePlatformEngineer>
        ),
      },
      {
        path: "tools/add",
        element: (
          <RequirePlatformEngineer>
            <ToolFormPage />
          </RequirePlatformEngineer>
        ),
      },
      {
        path: "tools/:name/edit",
        element: (
          <RequirePlatformEngineer>
            <ToolFormPage />
          </RequirePlatformEngineer>
        ),
      },

      // Audit Log — AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN (AC-5)
      // RequireAuditor guard is applied inside AuditLogPage itself.
      {
        path: "audit-log",
        element: <AuditLogPage />,
      },

      // Traces / Replay — AUDITOR, DEVOPS_SRE, SECURITY_OFFICER, or ADMIN
      {
        path: "traces",
        element: (
          <RequireAuditor>
            <ReplayExplorerPage />
          </RequireAuditor>
        ),
      },
      {
        path: "traces/:id",
        element: (
          <RequireAuditor>
            <TraceDetailPage />
          </RequireAuditor>
        ),
      },

    ],
  },
];
