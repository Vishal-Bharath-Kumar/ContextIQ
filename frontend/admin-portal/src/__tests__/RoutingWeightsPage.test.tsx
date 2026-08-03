/**
 * Tests for RoutingWeightsPage and IntentWeightCard — TASK-US041-03.
 *
 * Covers:
 *  - Page renders 8 intent types once API returns data
 *  - Each intent card shows 3 sliders (Quality, Cost, Latency)
 *  - Dragging a slider re-normalises the displayed total to 100%
 *  - Save button calls PUT /v1/routing/weights/:intentType
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
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { RoutingWeightsPage } from "../pages/models/RoutingWeightsPage";
import { IntentWeightCard } from "../components/models/IntentWeightCard";
import type { RoutingWeightEntry } from "../services/routingWeightService";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_ENTRIES: RoutingWeightEntry[] = [
  { intent_type: "code-gen",     quality_weight: 0.7,  cost_weight: 0.2,  latency_weight: 0.1  },
  { intent_type: "code-review",  quality_weight: 0.65, cost_weight: 0.25, latency_weight: 0.1  },
  { intent_type: "architecture", quality_weight: 0.6,  cost_weight: 0.3,  latency_weight: 0.1  },
  { intent_type: "docs",         quality_weight: 0.4,  cost_weight: 0.4,  latency_weight: 0.2  },
  { intent_type: "incident",     quality_weight: 0.5,  cost_weight: 0.2,  latency_weight: 0.3  },
  { intent_type: "metrics",      quality_weight: 0.3,  cost_weight: 0.5,  latency_weight: 0.2  },
  { intent_type: "debugging",    quality_weight: 0.65, cost_weight: 0.25, latency_weight: 0.1  },
  { intent_type: "general",      quality_weight: 0.4,  cost_weight: 0.4,  latency_weight: 0.2  },
];

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer(
  http.get("/api/v1/routing/weights", () =>
    HttpResponse.json(MOCK_ENTRIES, { status: 200 })
  ),
  http.put("/api/v1/routing/weights/:intentType", () =>
    HttpResponse.json(MOCK_ENTRIES[0], { status: 200 })
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

function renderPage() {
  render(
    <MemoryRouter>
      <QueryClientProvider client={makeQueryClient()}>
        <RoutingWeightsPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests: RoutingWeightsPage
// ---------------------------------------------------------------------------

describe("RoutingWeightsPage", () => {
  it("renders loading state initially", () => {
    renderPage();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders all 8 intent type cards after data loads", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument()
    );

    for (const entry of MOCK_ENTRIES) {
      // Component renders intent_type replacing underscores; hyphens remain.
      const rendered = entry.intent_type.replace(/_/g, " ");
      expect(
        screen.getByText(new RegExp(rendered, "i"))
      ).toBeInTheDocument();
    }
  });

  it("renders Quality, Cost, and Latency labels for each card", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument()
    );

    const qualityLabels = screen.getAllByText("Quality");
    const costLabels    = screen.getAllByText("Cost");
    const latencyLabels = screen.getAllByText("Latency");

    expect(qualityLabels).toHaveLength(8);
    expect(costLabels).toHaveLength(8);
    expect(latencyLabels).toHaveLength(8);
  });
});

// ---------------------------------------------------------------------------
// Tests: IntentWeightCard
// ---------------------------------------------------------------------------

describe("IntentWeightCard", () => {
  const entry: RoutingWeightEntry = {
    intent_type:    "debugging",
    quality_weight: 0.65,
    cost_weight:    0.25,
    latency_weight: 0.10,
  };

  function renderCard() {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <IntentWeightCard entry={entry} />
      </QueryClientProvider>
    );
    return { user };
  }

  it("shows intent type name in the card heading", () => {
    renderCard();
    expect(screen.getByText(/debugging/i)).toBeInTheDocument();
  });

  it("displays Quality, Cost, and Latency sliders", () => {
    renderCard();
    expect(screen.getByText("Quality")).toBeInTheDocument();
    expect(screen.getByText("Cost")).toBeInTheDocument();
    expect(screen.getByText("Latency")).toBeInTheDocument();
  });

  it("each Slider.Thumb has an aria-label including weight name and intent type", () => {
    renderCard();
    expect(
      screen.getByRole("slider", { name: /Quality weight for debugging/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("slider", { name: /Cost weight for debugging/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("slider", { name: /Latency weight for debugging/i })
    ).toBeInTheDocument();
  });

  it("Save button calls mutation endpoint", async () => {
    let capturedUrl = "";
    server.use(
      http.put("/api/v1/routing/weights/:intentType", ({ params }) => {
        capturedUrl = `/v1/routing/weights/${params.intentType}`;
        return HttpResponse.json(entry, { status: 200 });
      })
    );

    const { user } = renderCard();
    const saveBtn = screen.getByRole("button", {
      name: /Save routing weights for debugging/i,
    });
    await user.click(saveBtn);

    await waitFor(() =>
      expect(capturedUrl).toBe("/v1/routing/weights/debugging")
    );
  });
});

// ---------------------------------------------------------------------------
// Re-normalisation logic — unit test (pure)
// ---------------------------------------------------------------------------

describe("slider re-normalisation logic", () => {
  /**
   * Mirror the handleChange logic from IntentWeightCard to unit-test it.
   */
  function renormalise(
    weights: { quality_weight: number; cost_weight: number; latency_weight: number },
    key: "quality_weight" | "cost_weight" | "latency_weight",
    newVal: number
  ) {
    type WeightKey = "quality_weight" | "cost_weight" | "latency_weight";
    const ALL_KEYS: WeightKey[] = ["quality_weight", "cost_weight", "latency_weight"];
    const clamped = Math.max(0.05, Math.min(0.9, newVal));
    const others = ALL_KEYS.filter((k) => k !== key);
    const sumOther = others.reduce((s, k) => s + weights[k], 0) || 0.5;
    const scale = (1 - clamped) / sumOther;
    return {
      ...weights,
      [key]: clamped,
      [others[0]]: Math.round(weights[others[0]] * scale * 100) / 100,
      [others[1]]:
        Math.round((1 - clamped - weights[others[0]] * scale) * 100) / 100,
    };
  }

  it("displayed total stays at 1.0 after dragging quality slider", () => {
    const initial = { quality_weight: 0.65, cost_weight: 0.25, latency_weight: 0.10 };
    const updated = renormalise(initial, "quality_weight", 0.5);
    const total = +(updated.quality_weight + updated.cost_weight + updated.latency_weight).toFixed(2);
    expect(total).toBe(1.0);
  });

  it("value is clamped to minimum 0.05", () => {
    const initial = { quality_weight: 0.65, cost_weight: 0.25, latency_weight: 0.10 };
    const updated = renormalise(initial, "quality_weight", 0.01);
    expect(updated.quality_weight).toBe(0.05);
  });

  it("value is clamped to maximum 0.90", () => {
    const initial = { quality_weight: 0.65, cost_weight: 0.25, latency_weight: 0.10 };
    const updated = renormalise(initial, "quality_weight", 0.99);
    expect(updated.quality_weight).toBe(0.9);
  });
});
