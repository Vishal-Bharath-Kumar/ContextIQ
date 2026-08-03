/**
 * ConnectorToggle — React Testing Library tests.
 *
 * Covers TASK-US039-03 DoD items:
 *  - aria-label reflects action (Enable/Disable), not state (AC-7)
 *  - Clicking fires PATCH /v1/knowledge-sources/{id}/status (AC-4)
 *  - Toggle is keyboard-operable (Space toggles Radix UI Switch natively) (AC-7)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  describe,
  it,
  expect,
  beforeAll,
  afterEach,
  afterAll,
  vi,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ConnectorToggle } from "../components/connectors/ConnectorToggle";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderToggle(connectorId: string, enabled: boolean) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <ConnectorToggle connectorId={connectorId} enabled={enabled} />
    </QueryClientProvider>
  );
  return { user };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ConnectorToggle", () => {
  it("renders aria-label='Enable connector' when connector is inactive", () => {
    renderToggle("ks-001", false);
    expect(
      screen.getByRole("switch", { name: "Enable connector" })
    ).toBeInTheDocument();
  });

  it("renders aria-label='Disable connector' when connector is active", () => {
    renderToggle("ks-002", true);
    expect(
      screen.getByRole("switch", { name: "Disable connector" })
    ).toBeInTheDocument();
  });

  it("fires PATCH /v1/knowledge-sources/{id}/status with active=true when enabling", async () => {
    let capturedBody: unknown = null;
    server.use(
      http.patch("/api/v1/knowledge-sources/ks-003/status", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({}, { status: 200 });
      })
    );

    const { user } = renderToggle("ks-003", false);
    await user.click(screen.getByRole("switch", { name: "Enable connector" }));

    await waitFor(() => {
      expect(capturedBody).toEqual({ active: true });
    });
  });

  it("fires PATCH /v1/knowledge-sources/{id}/status with active=false when disabling", async () => {
    let capturedBody: unknown = null;
    server.use(
      http.patch("/api/v1/knowledge-sources/ks-004/status", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({}, { status: 200 });
      })
    );

    const { user } = renderToggle("ks-004", true);
    await user.click(screen.getByRole("switch", { name: "Disable connector" }));

    await waitFor(() => {
      expect(capturedBody).toEqual({ active: false });
    });
  });

  it("is keyboard-operable: Space key fires the mutation", async () => {
    const patchSpy = vi.fn(() => HttpResponse.json({}, { status: 200 }));
    server.use(
      http.patch("/api/v1/knowledge-sources/ks-005/status", patchSpy)
    );

    const { user } = renderToggle("ks-005", false);
    const toggle = screen.getByRole("switch", { name: "Enable connector" });
    toggle.focus();
    await user.keyboard(" ");

    await waitFor(() => {
      expect(patchSpy).toHaveBeenCalledTimes(1);
    });
  });
});
