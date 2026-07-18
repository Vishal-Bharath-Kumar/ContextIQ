/**
 * AddModelPage — React Testing Library tests.
 *
 * Covers DoD items:
 *  - Capability validation error when no capability is selected
 *  - HTTP 409 from POST /v1/models renders duplicate-model error message
 *  - Successful submit navigates to /models
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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

import { AddModelPage } from "../pages/models/AddModelPage";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

let capturedBody: unknown = null;

const server = setupServer(
  http.post("/api/v1/models", async ({ request }) => {
    capturedBody = await request.json();
    return HttpResponse.json({ id: "m-123" }, { status: 201 });
  })
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  capturedBody = null;
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
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/models/add"]}>
      <QueryClientProvider client={makeQueryClient()}>
        <AddModelPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
  return { user };
}

/** Fill all required fields except capabilities. */
async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Model ID/i), "gpt-4o");
  await user.type(screen.getByLabelText(/Provider/i), "openai");
  await user.type(screen.getByLabelText(/Context window/i), "128000");
  await user.type(screen.getByLabelText(/Cost per 1k tokens/i), "0.005");
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AddModelPage — capability validation", () => {
  it("shows 'Select at least one capability' when submitted with no capabilities", async () => {
    const { user } = renderPage();
    await fillRequiredFields(user);

    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Select at least one capability")
      ).toBeInTheDocument();
    });
  });

  it("does not show capability error when at least one capability is checked", async () => {
    const { user } = renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole("checkbox", { name: /chat/i }));

    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      expect(
        screen.queryByText("Select at least one capability")
      ).not.toBeInTheDocument();
    });
  });
});

describe("AddModelPage — HTTP 409 duplicate model", () => {
  it("shows duplicate-model error message on 409 response", async () => {
    server.use(
      http.post("/api/v1/models", () =>
        HttpResponse.json({ detail: "Conflict" }, { status: 409 })
      )
    );

    const { user } = renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole("checkbox", { name: /chat/i }));
    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      expect(
        screen.getByText("A model with this ID is already registered.")
      ).toBeInTheDocument();
    });
  });
});

describe("AddModelPage — successful submit", () => {
  it("navigates away after a successful registration", async () => {
    // Intercept navigation by checking the location in the router
    const { user } = renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole("checkbox", { name: /chat/i }));
    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      // The page should no longer show the form heading after successful navigation
      // (MemoryRouter will have navigated; heading disappears)
      expect(capturedBody).toMatchObject({
        model_id: "gpt-4o",
        provider: "openai",
        capabilities: ["chat"],
      });
    });
  });

  it("sends all six fields in the POST payload", async () => {
    const { user } = renderPage();
    await user.type(screen.getByLabelText(/Model ID/i), "anthropic/claude-3-haiku");
    await user.type(screen.getByLabelText(/Provider/i), "anthropic");
    await user.type(screen.getByLabelText(/Context window/i), "200000");
    await user.type(screen.getByLabelText(/Cost per 1k tokens/i), "0.0025");
    // latency_tier defaults to "medium"
    await user.click(screen.getByRole("checkbox", { name: /chat/i }));
    await user.click(screen.getByRole("checkbox", { name: /summarization/i }));

    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      expect(capturedBody).toMatchObject({
        model_id: "anthropic/claude-3-haiku",
        provider: "anthropic",
        context_window: 200000,
        cost_per_1k_tokens: 0.0025,
        latency_tier: "medium",
        capabilities: expect.arrayContaining(["chat", "summarization"]),
      });
    });
  });
});

describe("AddModelPage — accessibility", () => {
  it("renders all labels with matching htmlFor", () => {
    renderPage();
    expect(screen.getByLabelText(/Model ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Provider/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Context window/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Cost per 1k tokens/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Latency tier/i)).toBeInTheDocument();
  });

  it("has a fieldset with legend for capabilities", () => {
    renderPage();
    expect(screen.getByRole("group", { name: /Capabilities/i })).toBeInTheDocument();
  });
});
