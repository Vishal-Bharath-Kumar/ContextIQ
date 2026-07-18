/**
 * ConnectorListPage — React Testing Library tests.
 *
 * Covers TASK-US039-05 DoD items for AC-1:
 *  - Renders a row per connector with name and status badge aria-label
 *  - document_count formatted with thousands separator
 *  - "Never" when last_sync_at is null
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, beforeAll, afterEach, afterAll } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { ConnectorListPage } from "../pages/connectors/ConnectorListPage";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

const MOCK_CONNECTORS = [
  {
    id: "a1b2",
    name: "GitHub Docs",
    connector_type: "github",
    status: "active",
    last_sync_at: new Date().toISOString(),
    document_count: 1234,
  },
  {
    id: "c3d4",
    name: "Confluence KB",
    connector_type: "confluence",
    status: "error",
    last_sync_at: null,
    document_count: 0,
  },
];

const server = setupServer(
  http.get("/api/v1/knowledge-sources", () => HttpResponse.json(MOCK_CONNECTORS))
);

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

function renderPage() {
  render(
    <MemoryRouter>
      <QueryClientProvider client={makeQueryClient()}>
        <ConnectorListPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// AC-1 tests
// ---------------------------------------------------------------------------

describe("ConnectorListPage — AC-1", () => {
  it("renders a row for each connector with name and status badge", async () => {
    renderPage();
    expect(await screen.findByText("GitHub Docs")).toBeInTheDocument();
    expect(await screen.findByText("Confluence KB")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Connector status: Active")
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Connector status: Error")
    ).toBeInTheDocument();
  });

  it("shows document_count with thousands separator", async () => {
    renderPage();
    expect(await screen.findByText("1,234")).toBeInTheDocument();
  });

  it("shows 'Never' when last_sync_at is null", async () => {
    renderPage();
    expect(await screen.findByText("Never")).toBeInTheDocument();
  });

  it("shows loading state before data arrives", () => {
    server.use(
      http.get("/api/v1/knowledge-sources", async () => {
        await new Promise(() => {}); // never resolves
        return HttpResponse.json([]);
      })
    );
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows error state when the request fails", async () => {
    server.use(
      http.get("/api/v1/knowledge-sources", () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 })
      )
    );
    renderPage();
    expect(
      await screen.findByRole("alert")
    ).toBeInTheDocument();
  });
});
