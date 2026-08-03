/**
 * PolicyAuditTrailPanel — AC-6 tests.
 *
 * TASK-US040-05: Verifies the panel renders audit entries with actor and
 * formatted timestamp, shows a loading state, and handles empty results.
 */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  describe,
  it,
  expect,
  beforeAll,
  afterEach,
  afterAll,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { PolicyAuditTrailPanel } from "../components/policies/PolicyAuditTrailPanel";
import type { AuditLogEntry } from "../services/policyService";

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const NOW_ISO = "2026-07-18T10:00:00.000Z";

const MOCK_ENTRIES: AuditLogEntry[] = [
  {
    id: "entry-1",
    event_type: "activated",
    actor_user_id: "alice@acme.com",
    detail: null,
    created_at: NOW_ISO,
  },
  {
    id: "entry-2",
    event_type: "created",
    actor_user_id: "bob@acme.com",
    detail: "Initial version",
    created_at: NOW_ISO,
  },
];

const server = setupServer(
  http.get("/api/v1/policies/:id/audit", () =>
    HttpResponse.json(MOCK_ENTRIES)
  )
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQC() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPanel(policyId: string) {
  const qc = makeQC();
  return render(
    <QueryClientProvider client={qc}>
      <PolicyAuditTrailPanel policyId={policyId} />
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests — AC-6
// ---------------------------------------------------------------------------

describe("PolicyAuditTrailPanel — AC-6", () => {
  it("renders each entry with event label, actor user ID, and timestamp", async () => {
    renderPanel("policy-1");

    expect(
      await screen.findByText("Policy activated")
    ).toBeInTheDocument();
    expect(screen.getByText("Policy created")).toBeInTheDocument();
    expect(screen.getAllByText("alice@acme.com")[0]).toBeInTheDocument();
    expect(screen.getAllByText("bob@acme.com")[0]).toBeInTheDocument();
    // Formatted timestamps rendered inside <time> elements
    expect(screen.getAllByText(/2026-07-18/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders detail text when present", async () => {
    renderPanel("policy-1");
    expect(await screen.findByText(/Initial version/)).toBeInTheDocument();
  });

  it("shows loading state while data is fetching", () => {
    server.use(
      http.get("/api/v1/policies/:id/audit", async () => {
        await new Promise(() => {}); // never resolves
        return HttpResponse.json([]);
      })
    );
    renderPanel("policy-1");
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows empty message when no entries exist", async () => {
    server.use(
      http.get("/api/v1/policies/:id/audit", () => HttpResponse.json([]))
    );
    renderPanel("policy-empty");
    expect(
      await screen.findByText(/No audit events recorded yet/)
    ).toBeInTheDocument();
  });
});
