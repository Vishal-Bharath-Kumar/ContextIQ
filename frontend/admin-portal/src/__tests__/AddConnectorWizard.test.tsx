/**
 * AddConnectorWizard — React Testing Library tests.
 *
 * Covers DoD items:
 *  - Step navigation (next/back restores saved values)
 *  - Cron validation error on invalid input
 *  - Form submission payload sent to POST /v1/knowledge-sources
 *
 * AC-2: All four fields (connector_type, vault_path, scope, sync_schedule)
 *       are merged and sent on final submit.
 * AC-7: Each step's legend is in the document; errors use role="alert";
 *       WizardStepper marks current step with aria-current="step".
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

import { AddConnectorPage } from "../pages/connectors/AddConnectorPage";

// ---------------------------------------------------------------------------
// MSW mock server
// ---------------------------------------------------------------------------

let capturedBody: unknown = null;

const server = setupServer(
  http.post("/api/v1/knowledge-sources", async ({ request }) => {
    capturedBody = await request.json();
    return HttpResponse.json({ id: "ks-123" }, { status: 201 });
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

function renderWizard() {
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/connectors/add"]}>
      <QueryClientProvider client={makeQueryClient()}>
        <AddConnectorPage />
      </QueryClientProvider>
    </MemoryRouter>
  );
  return { user };
}

// ---------------------------------------------------------------------------
// Step 1 → Step 2 navigation
// ---------------------------------------------------------------------------

describe("Step 1: Type selection", () => {
  it("renders the type selection step with a card for each connector type", () => {
    renderWizard();
    expect(
      screen.getByRole("radio", { name: "GitHub" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Confluence" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Jira" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Grafana" })
    ).toBeInTheDocument();
  });

  it("marks step 1 as current via aria-current='step'", () => {
    renderWizard();
    const stepItems = screen.getAllByRole("listitem");
    expect(stepItems[0]).toHaveAttribute("aria-current", "step");
    expect(stepItems[1]).not.toHaveAttribute("aria-current");
  });

  it("advances to step 2 after selecting a type and entering a name", async () => {
    const { user } = renderWizard();

    await user.click(screen.getByRole("radio", { name: "GitHub" }));
    await user.type(screen.getByRole("textbox", { name: /connector name/i }), "my-github");
    await user.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() =>
      expect(screen.getByRole("group", { name: /credentials/i })).toBeInTheDocument()
    );
  });

  it("shows validation error when no type is selected and name is empty", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => {
      const alerts = screen.getAllByRole("alert");
      expect(alerts.length).toBeGreaterThan(0);
    });
  });
});

// ---------------------------------------------------------------------------
// Step 2 → Back → Step 2 (values restored)
// ---------------------------------------------------------------------------

describe("Step navigation: back restores saved values", () => {
  async function advanceToStep2(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("radio", { name: "Confluence" }));
    await user.type(
      screen.getByRole("textbox", { name: /connector name/i }),
      "my-confluence"
    );
    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() =>
      expect(screen.getByLabelText(/vault secret path/i)).toBeInTheDocument()
    );
  }

  it("going back from step 2 returns to step 1 with connector type still selected", async () => {
    const { user } = renderWizard();
    await advanceToStep2(user);

    await user.click(screen.getByRole("button", { name: /back/i }));

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Confluence" })).toBeChecked()
    );
    expect(
      (screen.getByRole("textbox", { name: /connector name/i }) as HTMLInputElement).value
    ).toBe("my-confluence");
  });
});

// ---------------------------------------------------------------------------
// Step 4: Cron validation error
// ---------------------------------------------------------------------------

describe("Step 4: Schedule cron validation", () => {
  async function navigateToStep4(user: ReturnType<typeof userEvent.setup>) {
    // Step 1
    await user.click(screen.getByRole("radio", { name: "Jira" }));
    await user.type(
      screen.getByRole("textbox", { name: /connector name/i }),
      "my-jira"
    );
    await user.click(screen.getByRole("button", { name: /next/i }));

    // Step 2
    await waitFor(() =>
      expect(screen.getByLabelText(/vault secret path/i)).toBeInTheDocument()
    );
    await user.type(
      screen.getByLabelText(/vault secret path/i),
      "secret/data/connectors/jira/my-cloud-token"
    );
    await user.click(screen.getByRole("button", { name: /next/i }));

    // Step 3
    await waitFor(() =>
      expect(screen.getByLabelText(/jira project key/i)).toBeInTheDocument()
    );
    await user.type(screen.getByLabelText(/jira project key/i), "PLATFORM");
    await user.click(screen.getByRole("button", { name: /next/i }));

    // Step 4
    await waitFor(() =>
      expect(screen.getByLabelText(/cron expression/i)).toBeInTheDocument()
    );
  }

  it("shows inline error for invalid cron expression", async () => {
    const { user } = renderWizard();
    await navigateToStep4(user);

    await user.type(screen.getByLabelText(/cron expression/i), "not-a-cron");
    await user.click(screen.getByRole("button", { name: /save connector/i }));

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent(/valid cron expression/i);
    });
  });

  it("accepts a valid cron expression and submits all four fields", async () => {
    const { user } = renderWizard();
    await navigateToStep4(user);

    await user.type(screen.getByLabelText(/cron expression/i), "0 2 * * *");
    await user.click(screen.getByRole("button", { name: /save connector/i }));

    await waitFor(() =>
      expect(capturedBody).toMatchObject({
        connector_type: "jira",
        name: "my-jira",
        vault_path: "secret/data/connectors/jira/my-cloud-token",
        scope: "PLATFORM",
        sync_schedule: "0 2 * * *",
      })
    );
  });

  it("accepts a @hourly shorthand cron", async () => {
    const { user } = renderWizard();
    await navigateToStep4(user);

    await user.type(screen.getByLabelText(/cron expression/i), "@hourly");
    await user.click(screen.getByRole("button", { name: /save connector/i }));

    await waitFor(() =>
      expect(capturedBody).toMatchObject({ sync_schedule: "@hourly" })
    );
  });
});

// ---------------------------------------------------------------------------
// WizardStepper accessibility (AC-7)
// ---------------------------------------------------------------------------

describe("WizardStepper aria-current marks", () => {
  it("marks step 2 as current after advancing once", async () => {
    const { user } = renderWizard();

    await user.click(screen.getByRole("radio", { name: "GitHub" }));
    await user.type(
      screen.getByRole("textbox", { name: /connector name/i }),
      "test"
    );
    await user.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => {
      const stepItems = screen.getAllByRole("listitem");
      expect(stepItems[0]).not.toHaveAttribute("aria-current");
      expect(stepItems[1]).toHaveAttribute("aria-current", "step");
    });
  });
});
