/**
 * AddModelForm (via AddModelPage) — React Testing Library tests.
 *
 * Covers:
 *  AC-2: submitting with no capability selected shows validation error
 *  AC-2: server-side 409 shows inline "already registered" message
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
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { AddModelPage } from "../pages/models/AddModelPage";

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer(
  http.post("/api/v1/models", async () =>
    HttpResponse.json({ id: "new-model-id" }, { status: 201 })
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

async function fillBaseFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Model ID/i), "gpt-4o");
  await user.type(screen.getByLabelText(/Provider/i), "openai");
  await user.type(screen.getByLabelText(/Context window/i), "128000");
  await user.type(screen.getByLabelText(/Cost per 1k tokens/i), "0.005");
}

// ---------------------------------------------------------------------------
// AC-2: capability validation
// ---------------------------------------------------------------------------

describe("AddModelPage — AC-2 capability validation", () => {
  it("shows 'Select at least one capability' when submitted with no capabilities", async () => {
    const { user } = renderPage();
    await fillBaseFields(user);

    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/select at least one capability/i)
      ).toBeInTheDocument();
    });
  });

  it("does not show capability error when at least one capability is checked", async () => {
    const { user } = renderPage();
    await fillBaseFields(user);
    await user.click(screen.getByRole("checkbox", { name: /chat/i }));

    await user.click(screen.getByRole("button", { name: /Register Model/i }));

    await waitFor(() => {
      expect(
        screen.queryByText(/select at least one capability/i)
      ).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// AC-2: 409 duplicate error
// ---------------------------------------------------------------------------

describe("AddModelPage — AC-2 duplicate 409 error", () => {
  it("shows 'already registered' message when server returns 409", async () => {
    server.use(
      http.post("/api/v1/models", () =>
        HttpResponse.json(
          { detail: "Model 'gpt-4o' is already registered." },
          { status: 409 }
        )
      )
    );

    const { user } = renderPage();
    await fillBaseFields(user);
    await user.click(screen.getByRole("checkbox", { name: /chat/i }));

    fireEvent.submit(
      screen
        .getByRole("button", { name: /Register Model/i })
        .closest("form")!
    );

    await waitFor(() => {
      expect(
        screen.getByText(/already registered/i)
      ).toBeInTheDocument();
    });
  });
});
