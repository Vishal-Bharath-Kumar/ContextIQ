/**
 * ModelListPage — React Testing Library tests.
 *
 * Covers:
 *  AC-1: table renders model_id, provider, context_window, cost, latency badge, capability tags
 *  AC-5: deactivation toggle calls PATCH /api/v1/models/{id}/status
 *
 * TASK-US041-05
 */
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
} from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ModelListPage } from "../pages/models/ModelListPage";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_MODELS = [
  {
    id: "m1",
    model_id: "gpt-4o",
    provider: "openai",
    context_window: 128000,
    cost_per_1k_tokens: 0.005,
    latency_tier: "medium",
    capabilities: ["chat", "function_call"],
    is_active: true,
    created_at: new Date().toISOString(),
  },
];

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

let patchBody: unknown = null;

const server = setupServer(
  http.get("/api/v1/models", () => HttpResponse.json(MOCK_MODELS, { status: 200 })),
  http.patch("/api/v1/models/:id/status", async ({ request }) => {
    patchBody = await request.json();
    return HttpResponse.json(
      { ...MOCK_MODELS[0], is_active: false },
      { status: 200 }
    );
  })
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  patchBody = null;
});
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderPage() {
  render(
    <MemoryRouter>
      <QueryClientProvider client={makeQueryClient()}>
        <ModelListPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// AC-1: model list columns
// ---------------------------------------------------------------------------

describe("ModelListPage — AC-1", () => {
  it("renders model_id, provider, context window, cost and latency badge", async () => {
    renderPage();
    expect(await screen.findByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("128,000")).toBeInTheDocument();
    expect(screen.getByText("$0.0050")).toBeInTheDocument();
    expect(screen.getByLabelText("Latency: Medium")).toBeInTheDocument();
  });

  it("renders capability tags for each model", async () => {
    renderPage();
    expect(await screen.findByText("chat")).toBeInTheDocument();
    expect(screen.getByText("function_call")).toBeInTheDocument();
  });

  it("shows loading state before data arrives", () => {
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("does not render a register model action in the header", async () => {
    renderPage();
    await screen.findByText("gpt-4o");
    expect(screen.queryByRole("link", { name: /register model/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /install model/i })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AC-5: deactivation toggle
// ---------------------------------------------------------------------------

describe("ModelRow deactivation toggle — AC-5", () => {
  it("calls PATCH /api/v1/models/:id/status when toggle is switched off", async () => {
    renderPage();
    const toggle = await screen.findByRole("switch", {
      name: /deactivate gpt-4o/i,
    });
    toggle.click();
    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });
    expect((patchBody as { is_active: boolean }).is_active).toBe(false);
  });
});
