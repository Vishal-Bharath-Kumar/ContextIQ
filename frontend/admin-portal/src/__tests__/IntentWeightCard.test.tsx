/**
 * IntentWeightCard — React Testing Library tests.
 *
 * Covers:
 *  AC-3: three sliders with correct aria-labels render for each intent type
 *  AC-3: percentage values (0–100%) are displayed next to each slider
 *
 * TASK-US041-05
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { beforeAll, afterEach, afterAll } from "vitest";

import { IntentWeightCard } from "../components/models/IntentWeightCard";
import type { RoutingWeightEntry } from "../services/routingWeightService";

// ---------------------------------------------------------------------------
// MSW server (mutations in card call PUT)
// ---------------------------------------------------------------------------

const server = setupServer(
  http.put("/api/v1/routing/weights/:intentType", () =>
    HttpResponse.json({}, { status: 200 })
  )
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

function renderCard(entry: RoutingWeightEntry) {
  render(
    <MemoryRouter>
      <QueryClientProvider client={makeQueryClient()}>
        <IntentWeightCard entry={entry} />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

const CODE_GEN_ENTRY: RoutingWeightEntry = {
  intent_type: "code_generation",
  quality_weight: 0.70,
  cost_weight: 0.20,
  latency_weight: 0.10,
};

// ---------------------------------------------------------------------------
// AC-3: slider aria-labels
// ---------------------------------------------------------------------------

describe("IntentWeightCard — AC-3 slider aria-labels", () => {
  it("renders Quality slider with correct aria-label", () => {
    renderCard(CODE_GEN_ENTRY);
    expect(
      screen.getAllByLabelText(/quality weight for code_generation/i).length
    ).toBeGreaterThan(0);
  });

  it("renders Cost slider with correct aria-label", () => {
    renderCard(CODE_GEN_ENTRY);
    expect(
      screen.getAllByLabelText(/cost weight for code_generation/i).length
    ).toBeGreaterThan(0);
  });

  it("renders Latency slider with correct aria-label", () => {
    renderCard(CODE_GEN_ENTRY);
    expect(
      screen.getAllByLabelText(/latency weight for code_generation/i).length
    ).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC-3: percentage values displayed
// ---------------------------------------------------------------------------

describe("IntentWeightCard — AC-3 percentage display", () => {
  it("displays 70%, 20%, and 10% for the given entry", () => {
    renderCard(CODE_GEN_ENTRY);
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("10%")).toBeInTheDocument();
  });

  it("renders all three slider labels (Quality, Cost, Latency)", () => {
    renderCard(CODE_GEN_ENTRY);
    expect(screen.getByText("Quality")).toBeInTheDocument();
    expect(screen.getByText("Cost")).toBeInTheDocument();
    expect(screen.getByText("Latency")).toBeInTheDocument();
  });
});
